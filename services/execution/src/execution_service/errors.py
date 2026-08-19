"""Execution adapter errors — all fail-closed (TRD 4.9, 5.10)."""

from __future__ import annotations


class ExecutionError(Exception):
    """Base class for execution adapter failures."""


class TokenStoreError(ExecutionError):
    """Decision-token store unavailable (Redis down). Fail-closed: no token,
    no broadcast. Prevents an unguarded broadcast under Redis outage."""


class TokenConsumedError(ExecutionError):
    """The decision token was already used. This is the single-use gate —
    a second submit for the same decision is rejected (race / replay)."""


class TokenInvalidError(ExecutionError):
    """The submitted decision token does not match the issued one."""


class DecisionNotApprovedError(ExecutionError):
    """The transaction is not in an executable (approved) state."""


class SignedTxInvalidError(ExecutionError):
    """The signed raw transaction failed integrity validation — the signer
    attempted to broadcast something different from what was screened."""


class NonceMismatchError(SignedTxInvalidError):
    """Signed nonce differs from the Redis-locked reservation."""


class GasCeilingError(SignedTxInvalidError):
    """Signed gas exceeds the policy/chain ceiling (FR-CHAIN-02, TRD 5.8)."""


class BroadcastError(ExecutionError):
    """The RPC rejected the broadcast, or the broadcast call failed."""


class ConfirmationTimeoutError(ExecutionError):
    """The transaction did not reach the confirmation depth in time."""


class StuckTransactionError(ExecutionError):
    """The broadcast transaction is stuck (unconfirmed beyond threshold)."""


class ReorgDetectedError(ExecutionError):
    """A previously confirmed transaction's block was orphaned."""
