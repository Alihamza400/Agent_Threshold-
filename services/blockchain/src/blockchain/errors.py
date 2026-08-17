"""Blockchain service errors — all fail-closed (TRD 4.9)."""

from __future__ import annotations


class BlockchainError(Exception):
    """Base class for blockchain integration errors."""


class RPCError(BlockchainError):
    """Transport-level or JSON-RPC-level failure from a provider."""


class CrossCheckMismatchError(RPCError):
    """Primary and fallback providers disagreed on a deterministic read (5.4).

    Threat model: a malicious or compromised RPC could return fabricated
    state; disagreement escalates to fail-closed rather than trusting either.
    """


class NoProviderConfiguredError(BlockchainError):
    """No RPC endpoint is configured for the requested chain."""


class GasExceedsCeilingError(BlockchainError):
    """Estimated gas (with buffer) exceeds the policy gas ceiling (FR-CHAIN-02)."""

    def __init__(self, estimated: int, ceiling: int) -> None:
        super().__init__(
            f"estimated gas {estimated} exceeds policy ceiling {ceiling}"
        )
        self.estimated = estimated
        self.ceiling = ceiling


class NonceReservationError(BlockchainError):
    """Redis-backed nonce allocation failed (fail-closed, FR-CHAIN-03)."""


class OracleError(BlockchainError):
    """Price oracle failure (fail-closed)."""