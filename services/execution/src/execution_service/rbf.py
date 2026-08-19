"""Stuck-tx handling: RBF / cancel with re-screening (task 8.5, TRD 5.10).

A broadcast tx that never mines within `stuck_after_seconds` is flagged
`stuck`. Replacing it requires a NEW signed transaction from the agent and a
fresh single-use decision token. The replacement is RE-SCREENED through the
screening pipeline before broadcast:

  - RBF:    same intent (to/value/calldata), higher gas price, same nonce
  - cancel: zero-value self-transfer to clear the nonce, same nonce

Re-screening is the plan's explicit requirement ("requiring re-screening of
the replacement transaction") — a replacement is a new decision, not a blind
re-broadcast. The `rescreen` callable is injected so tests can fake the
pipeline; production wires the orchestrator Pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from at_shared.models import Transaction
from at_shared.schemas.tx import Decision, DecisionType, ScreenRequest
from blockchain.config import ChainConfig
from blockchain.errors import RPCError
from blockchain.rpc import RPCClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from execution_service.errors import (
    DecisionNotApprovedError,
    GasCeilingError,
    SignedTxInvalidError,
    TokenConsumedError,
)
from execution_service.tokens import DecisionTokenStore
from execution_service.validation import decode_signed_tx

logger = logging.getLogger("execution_service.rbf")

Rescreen = Callable[[ScreenRequest, str], Awaitable[Decision]]


def _gas_price(decoded: dict) -> int:
    for key in ("maxFeePerGas", "gasPrice"):
        value = decoded.get(key)
        if value is not None and int(value) > 0:
            return int(value)
    return 0


@dataclass(frozen=True)
class ReplaceResult:
    tx_hash: str
    mode: str


def flag_stuck(
    session_factory: Callable[[], Session],
    *,
    stuck_after_seconds: float,
    limit: int = 200,
) -> list[str]:
    """Mark broadcast txs with no confirmation past the threshold as stuck."""
    cutoff = datetime.now(UTC) - timedelta(seconds=stuck_after_seconds)
    flagged: list[str] = []
    with session_factory() as session:
        rows = session.scalars(
            select(Transaction)
            .where(
                Transaction.status == "broadcast",
                Transaction.broadcast_at.is_not(None),
                Transaction.broadcast_at < cutoff,
                Transaction.stuck_at.is_(None),
            )
            .limit(limit)
        ).all()
        for tx in rows:
            tx.status = "stuck"
            tx.stuck_at = datetime.now(UTC)
            flagged.append(tx.id)
        session.commit()
    if flagged:
        logger.error("stuck transactions flagged (RBF/cancel required): %s", flagged)
    return flagged


class StuckTxHandler:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        tokens: DecisionTokenStore,
        chain_resolver: Callable[[str], ChainConfig | None],
        rpc_factory: Callable[[ChainConfig], RPCClient],
        rescreen: Rescreen,
        rbf_gas_bump_pct: float = 20.0,
        cancel_gas_bump_pct: float = 20.0,
    ) -> None:
        self._session_factory = session_factory
        self._tokens = tokens
        self._chain_resolver = chain_resolver
        self._rpc_factory = rpc_factory
        self._rescreen = rescreen
        self.rbf_bump = rbf_gas_bump_pct / 100.0
        self.cancel_bump = cancel_gas_bump_pct / 100.0

    async def replace(
        self, transaction_id: str, decision_token: str, signed_raw: str, *, mode: str
    ) -> ReplaceResult:
        if mode not in {"rbf", "cancel"}:
            raise SignedTxInvalidError("mode must be 'rbf' or 'cancel'")
        if not self._tokens.consume(transaction_id, decision_token):
            raise TokenConsumedError(
                f"decision token for replacement of {transaction_id} is missing or used"
            )

        decoded = decode_signed_tx(signed_raw)
        with self._session_factory() as session:
            tx = session.get(Transaction, transaction_id)
            if tx is None or tx.status != "stuck":
                raise DecisionNotApprovedError(
                    f"transaction {transaction_id} is not stuck and replaceable"
                )
            self._validate_replacement(tx, decoded, mode)
            request = self._to_screen_request(tx, decoded)
            decision = await self._rescreen(request, tx.org_id)
            if decision.decision is not DecisionType.APPROVE:
                raise SignedTxInvalidError(
                    f"replacement re-screen did not approve: {decision.decision.value}"
                )

            claimed = session.execute(
                update(Transaction)
                .where(Transaction.id == transaction_id, Transaction.status == "stuck")
                .values(
                    status="broadcasting", broadcast_attempts=Transaction.broadcast_attempts + 1
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                raise TokenConsumedError(f"replacement for {transaction_id} already in progress")

            chain = self._chain_resolver(tx.chain_id)
            if chain is None or not chain.is_configured:
                tx.status = "stuck"
                session.commit()
                raise SignedTxInvalidError(f"no RPC provider configured for chain {tx.chain_id!r}")
            rpc = self._rpc_factory(chain)
            try:
                tx_hash = await rpc.send_raw_transaction(signed_raw)
            except RPCError as exc:
                tx.status = "stuck"
                session.commit()
                raise SignedTxInvalidError(f"replacement broadcast failed: {exc}") from exc

            tx.status = "broadcast"
            tx.tx_hash = tx_hash
            tx.broadcast_at = datetime.now(UTC)
            session.commit()
            return ReplaceResult(tx_hash=tx_hash, mode=mode)

    # ------------------------------------------------------------- internal
    def _validate_replacement(self, tx: Transaction, decoded: dict, mode: str) -> None:
        """The replacement must clear the SAME nonce and be the same intent."""
        if (decoded.get("from") or "").lower() != tx.from_address.lower():
            raise SignedTxInvalidError("replacement signed `from` differs from agent wallet")
        if int(decoded.get("nonce")) != tx.nonce:
            raise SignedTxInvalidError(
                f"replacement nonce {int(decoded.get('nonce'))} != stuck nonce {tx.nonce}"
            )

        if mode == "cancel":
            if (decoded.get("to") or "").lower() != tx.from_address.lower():
                raise SignedTxInvalidError("cancel replacement must send zero value to self")
            if int(decoded.get("value") or 0) != 0:
                raise SignedTxInvalidError("cancel replacement must be zero-value")
            min_gas = self._bumped_gas(tx, self.cancel_bump)
        else:  # rbf
            signed_to = (decoded.get("to") or "").lower() if decoded.get("to") else None
            if signed_to != (tx.to_address.lower() if tx.to_address else None):
                raise SignedTxInvalidError("RBF replacement `to` differs from original")
            if int(decoded.get("value") or 0) != tx.value_wei:
                raise SignedTxInvalidError("RBF replacement value differs from original")
            min_gas = self._bumped_gas(tx, self.rbf_bump)

        if min_gas is not None and _gas_price(decoded) < min_gas:
            raise GasCeilingError(
                f"replacement gas price {_gas_price(decoded)} below required bump {min_gas}"
            )

    @staticmethod
    def _bumped_gas(tx: Transaction, bump: float) -> int | None:
        if tx.gas_price_wei is None:
            return None
        return tx.gas_price_wei + int(tx.gas_price_wei * bump)

    @staticmethod
    def _to_screen_request(tx: Transaction, decoded: dict) -> ScreenRequest:
        return ScreenRequest(
            agent_id=tx.agent_id,
            chain_id=tx.chain_id,  # type: ignore[arg-type]  # validated to ChainId upstream
            from_address=tx.from_address,
            to_address=tx.to_address,
            value_wei=tx.value_wei,
            calldata=tx.calldata,
            gas_limit=tx.gas_limit,
            gas_price_wei=_gas_price(decoded) or tx.gas_price_wei,
            task_context=None,
        )
