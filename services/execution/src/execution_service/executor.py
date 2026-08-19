"""Execution adapter core: prepare -> signed submit -> broadcast (task 8.5).

Non-custodial broadcast of a pre-signed transaction for an approved decision.
The ordering of guards is deliberate:

  1. consume single-use decision token  (Redis, atomic) — race / replay gate
  2. conditional DB transition approved -> broadcasting (row-locked) — durable
     double-broadcast guard even if Redis were ever to lose the token
  3. signed-tx integrity + nonce + gas validation — the submitted payload must
     be exactly the screened-and-approved transaction
  4. Redis-locked nonce was allocated at `prepare` (FR-CHAIN-03)
  5. broadcast with exponential backoff; persistent failure reverts to
     `approved` and surfaces an alert (TRD 5.10) — never silently dropped
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from at_shared.models import Transaction
from blockchain.config import ChainConfig
from blockchain.errors import RPCError
from blockchain.nonce import NonceAllocator
from blockchain.rpc import RPCClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from execution_service.errors import (
    BroadcastError,
    DecisionNotApprovedError,
    ExecutionError,
    TokenConsumedError,
)
from execution_service.tokens import DecisionTokenStore
from execution_service.validation import decode_signed_tx, validate_signed_tx

logger = logging.getLogger("execution_service.executor")


@dataclass(frozen=True)
class PrepareResult:
    decision_token: str
    nonce: int
    chain_id: str


@dataclass(frozen=True)
class SubmitResult:
    tx_hash: str
    nonce: int
    chain_id: str


class ExecutionAdapter:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        tokens: DecisionTokenStore,
        nonce_allocator: NonceAllocator,
        chain_resolver: Callable[[str], ChainConfig | None],
        rpc_factory: Callable[[ChainConfig], RPCClient],
        max_broadcast_attempts: int = 5,
        backoff_base_seconds: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._session_factory = session_factory
        self._tokens = tokens
        self._nonces = nonce_allocator
        self._chain_resolver = chain_resolver
        self._rpc_factory = rpc_factory
        self.max_broadcast_attempts = max_broadcast_attempts
        self._backoff_base = backoff_base_seconds
        self._sleep = sleep

    # ------------------------------------------------------------------ API
    def prepare(self, transaction_id: str) -> PrepareResult:
        """Lock a nonce and mint the single-use token for an approved tx.

        Re-`prepare` after a failed broadcast reuses the same reserved nonce
        (no nonce gap) and simply re-mints the token.
        """
        with self._session_factory() as session:
            tx = session.get(Transaction, transaction_id)
            if tx is None or tx.status != "approved":
                raise DecisionNotApprovedError(
                    f"transaction {transaction_id} is not approved and executable"
                )
            if tx.nonce is None:
                tx.nonce = self._nonces.reserve(tx.from_address)
                session.commit()
            reserved_nonce = tx.nonce
        token = self._tokens.issue(tx.id)
        return PrepareResult(decision_token=token, nonce=reserved_nonce, chain_id=tx.chain_id)

    async def submit(
        self, transaction_id: str, decision_token: str, signed_raw: str
    ) -> SubmitResult:
        """Validate + broadcast the signed tx for an approved decision.

        Exactly one call can win the single-use token AND the conditional DB
        transition; every other caller gets TokenConsumedError.
        """
        if not self._tokens.consume(transaction_id, decision_token):
            raise TokenConsumedError(
                f"decision token for {transaction_id} is missing, expired, or already used"
            )

        with self._session_factory() as session:
            tx = session.get(Transaction, transaction_id)
            if tx is None or tx.status != "approved":
                raise TokenConsumedError(
                    f"transaction {transaction_id} is not in an executable state"
                )
            if tx.nonce is None:
                raise DecisionNotApprovedError(
                    f"transaction {transaction_id} has no reserved nonce; call prepare first"
                )
            reserved_nonce = tx.nonce
            # Durable double-broadcast guard: row-locked conditional transition.
            claimed = session.execute(
                update(Transaction)
                .where(Transaction.id == transaction_id, Transaction.status == "approved")
                .values(
                    status="broadcasting", broadcast_attempts=Transaction.broadcast_attempts + 1
                )
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                raise TokenConsumedError(
                    f"transaction {transaction_id} was already broadcast by another submit"
                )
            try:
                tx_hash = await self._broadcast(tx, signed_raw, reserved_nonce)
            except ExecutionError:
                # Revert within the SAME transaction so the attempt counter
                # survives; the caller may prepare (re-mint token) + resubmit.
                # (Real UPDATE — the in-memory attribute is untouched because
                # the claim used synchronize_session=False.)
                session.execute(
                    update(Transaction)
                    .where(Transaction.id == transaction_id, Transaction.status == "broadcasting")
                    .values(status="approved")
                    .execution_options(synchronize_session=False)
                )
                session.commit()
                raise
            tx.status = "broadcast"
            tx.tx_hash = tx_hash
            tx.broadcast_at = datetime.now(UTC)
            session.commit()
            return SubmitResult(tx_hash=tx_hash, nonce=reserved_nonce, chain_id=tx.chain_id)

    async def _broadcast(self, tx: Transaction, signed_raw: str, reserved_nonce: int) -> str:
        decoded = decode_signed_tx(signed_raw)
        validate_signed_tx(tx, decoded, reserved_nonce=reserved_nonce)

        chain = self._chain_resolver(tx.chain_id)
        if chain is None or not chain.is_configured:
            raise BroadcastError(f"no RPC provider configured for chain {tx.chain_id!r}")

        rpc = self._rpc_factory(chain)
        last_error: Exception | None = None
        for attempt in range(self.max_broadcast_attempts):
            try:
                return await rpc.send_raw_transaction(signed_raw)
            except RPCError as exc:
                last_error = exc
                logger.warning(
                    "broadcast attempt %s/%s failed for %s: %s",
                    attempt + 1,
                    self.max_broadcast_attempts,
                    tx.id,
                    exc,
                )
                if attempt + 1 < self.max_broadcast_attempts:
                    await self._sleep(self._backoff_base * (2**attempt))

        # Persistent failure: never silently drop the transaction; the caller
        # surfaces the alert and may prepare + resubmit a fresh signed tx (we
        # never persist raw signed payloads).
        raise BroadcastError(
            f"broadcast failed after {self.max_broadcast_attempts} attempts for {tx.id}: {last_error}"
        )

    def cancel(self, transaction_id: str) -> None:
        """Explicit cancel: invalidate the token and reject the approved tx."""
        self._tokens.revoke(transaction_id)
        with self._session_factory() as session:
            result = session.execute(
                update(Transaction)
                .where(Transaction.id == transaction_id, Transaction.status == "approved")
                .values(status="cancelled")
                .execution_options(synchronize_session=False)
            )
            session.commit()
            if result.rowcount != 1:
                raise DecisionNotApprovedError(
                    f"transaction {transaction_id} is not pending execution"
                )
