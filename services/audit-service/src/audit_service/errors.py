"""Audit-service errors — all fail-closed (FR-AUDIT-01).

The batching worker must never silently drop audit records: every failure
path keeps the pending batch intact and retries, escalating to a typed
error that operations can alarm on.
"""

from __future__ import annotations


class AuditError(Exception):
    """Base class for audit/anchoring errors."""


# Canonical MerkleError lives in at_shared.merkle (shared with the gateway);
# re-exported here so `from audit_service.errors import MerkleError` still works.
from at_shared.merkle import MerkleError  # noqa: E402, F401


class AnchorConfigurationError(AuditError):
    """Anchor contract / wallet / RPC not configured (fail-closed startup)."""


class AnchorSubmissionError(AuditError):
    """A batch could not be anchored after all attempts; buffer is retained."""

    def __init__(self, batch_id: int, root: bytes, attempts: int, cause: str) -> None:
        super().__init__(
            f"anchor batch {batch_id} (root {root.hex()}) failed after "
            f"{attempts} attempts: {cause}"
        )
        self.batch_id = batch_id
        self.root = root
        self.attempts = attempts


class AnchorVerificationError(AnchorSubmissionError):
    """The chain did not store the expected root for the submitted batch."""


class AnchorRevertedError(AnchorSubmissionError):
    """The submitted transaction reverted on-chain (status == 0)."""