"""HTTP client for the AgentThreshold screening API.

Fail-closed (SR-04): a transport failure, timeout, 5xx, or malformed response
raises `ScreeningUnavailableError` — the transaction must never be signed or
broadcast when the screening outcome is unknown. `screen_and_sign` invokes the
caller-provided signer ONLY on an APPROVE decision; REJECT, ESCALATE, and any
error raise instead.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from .errors import (
    ScreeningEscalatedError,
    ScreeningRejectedError,
    ScreeningUnavailableError,
    TransportError,
    UnauthorizedError,
)
from .schemas import Decision, DecisionType, ScreenRequest
from .signing import unsigned_tx_to_screen_request

__all__ = ["AgentThresholdClient"]


class AgentThresholdClient:
    """Client for ``POST /v1/transactions/screen``.

    Args:
        base_url: gateway origin, e.g. ``https://screen.agentthreshold.dev``.
        api_key: scoped API key shown once at creation (FR-AUTH-01).
        timeout: per-request timeout. The screening p95 is < 2s; 10s covers the
            worst-case multi-stage pipeline plus scheduling slack.
        max_retries: retries for TRANSPORT-LEVEL failures only (connect
            errors / 5xx). Retrying is safe because screening is read-only and
            advisory. Zero by default: fail-closed is the safer default.
        session: optional injected ``httpx.Client`` (tests / mTLS setups).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 0,
        session: httpx.Client | None = None,
    ) -> None:
        if not base_url or not api_key:
            raise ValueError("base_url and api_key are required")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._owns_session = session is None
        self._session = session or httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ API
    def screen(self, request: ScreenRequest) -> Decision:
        """Screen one transaction; returns the pipeline's Decision.

        Raises on transport/5xx/malformed responses (fail-closed). The
        Decision itself may be approve/reject/escalate — callers that want
        sign-or-raise behavior should use ``screen_and_sign``.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.post(
                    f"{self.base_url}/v1/transactions/screen",
                    headers=self._headers(),
                    json=request.model_dump(mode="json"),
                )
                return self._decode(response)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
            except httpx.HTTPStatusError:
                raise
            if attempt < self._max_retries:
                time.sleep(0.2 * (attempt + 1))
        raise TransportError(
            f"screening request failed after {self._max_retries} retries: {last_error}"
        )

    def screen_and_sign(
        self,
        signer: Callable[[dict[str, Any]], Any],
        *,
        agent_id: str,
        chain_id: Any,
        from_address: str,
        to_address: str | None = None,
        value_wei: int,
        calldata: str | None = None,
        gas_limit: int | None = None,
        gas_price_wei: int | None = None,
        token: str | None = None,
        task_context: str | None = None,
    ) -> Any:
        """Screen a transaction and sign it iff the pipeline approves.

        Non-custodial: ``signer`` is a callable the CALLER provides (it owns
        the private key / signing service). It is invoked only on APPROVE,
        with the approved unsigned tx dict. REJECT / ESCALATE / any error
        raise without invoking the signer.
        """
        request = ScreenRequest(
            agent_id=agent_id,
            chain_id=chain_id,
            from_address=from_address,
            to_address=to_address,
            value_wei=value_wei,
            calldata=calldata,
            gas_limit=gas_limit,
            gas_price_wei=gas_price_wei,
            token=token,
            task_context=task_context,
        )
        decision = self.screen(request)
        return self._sign_if_approved(signer, decision, request)

    def screen_and_sign_tx(
        self,
        signer: Callable[[dict[str, Any]], Any],
        unsigned_tx: dict[str, Any],
        *,
        agent_id: str,
        chain_id: Any,
        task_context: str | None = None,
    ) -> Any:
        """Normalize an unsigned EVM tx, screen it, and sign iff approved."""
        request = unsigned_tx_to_screen_request(
            unsigned_tx, agent_id=agent_id, chain_id=chain_id, task_context=task_context
        )
        decision = self.screen(request)
        return self._sign_if_approved(signer, decision, request)

    def close(self) -> None:
        """Close the underlying HTTP session (no-op when injected)."""
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> AgentThresholdClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------- internals
    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "agentthreshold-sdk/0.1.0",
        }

    def _decode(self, response: httpx.Response) -> Decision:
        if response.status_code == 401:
            raise UnauthorizedError("API key rejected (401); check the key value and agent scope")
        if response.status_code == 429:
            raise ScreeningUnavailableError(f"rate limited (429): {response.text}")
        if response.status_code >= 500:
            raise ScreeningUnavailableError(f"screening unavailable ({response.status_code})")
        if response.status_code != 200:
            raise TransportError(
                f"unexpected status {response.status_code} from screening API: {response.text[:200]}"
            )
        try:
            return Decision.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise ScreeningUnavailableError(f"malformed decision body: {exc}") from exc

    @staticmethod
    def _sign_if_approved(
        signer: Callable[[dict[str, Any]], Any],
        decision: Decision,
        request: ScreenRequest,
    ) -> Any:
        if decision.decision is DecisionType.APPROVE:
            return signer(_unsigned_tx(request))
        if decision.decision is DecisionType.REJECT:
            raise ScreeningRejectedError(decision)
        raise ScreeningEscalatedError(decision)


def _unsigned_tx(request: ScreenRequest) -> dict[str, Any]:
    """Round-trip a ScreenRequest back into the unsigned tx dict the signer sees."""
    tx: dict[str, Any] = {
        "from": request.from_address,
        "value": request.value_wei,
    }
    if request.to_address:
        tx["to"] = request.to_address
    if request.calldata:
        tx["data"] = request.calldata
    if request.gas_limit is not None:
        tx["gas"] = request.gas_limit
    if request.gas_price_wei is not None:
        tx["gasPrice"] = request.gas_price_wei
    return tx
