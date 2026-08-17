"""Canonical audit event leaves + persistence (FR-AUDIT-01).

Every auditable event (screening decision, policy change, ...) produces a
32-byte keccak256 leaf from a versioned canonical encoding, then an immutable
`AuditRecord` row. The audit-service batcher folds these leaves into Merkle
batches and anchors the root on-chain; the api-gateway can rebuild the proof
for any anchored record from the stored `event_hash` values alone.
"""

from __future__ import annotations

from at_shared.merkle import leaf_hash
from at_shared.models import AuditRecord
from at_shared.uuid7 import uuid7

LEAF_VERSION = "v1"


def audit_leaf(*parts: object) -> bytes:
    """Canonical, versioned leaf: keccak256("v1|part|part|...")."""
    canonical = LEAF_VERSION + "|" + "|".join(str(p) for p in parts)
    return leaf_hash(canonical.encode())


def write_audit_record(
    db: object,
    *,
    org_id: str,
    agent_id: str,
    transaction_id: str | None,
    event_type: str,
    details: dict,
    leaf: bytes,
) -> AuditRecord:
    """Persist an audit record (caller commits the surrounding transaction)."""
    record = AuditRecord(
        id=uuid7(),
        org_id=org_id,
        agent_id=agent_id,
        transaction_id=transaction_id,
        event_type=event_type,
        event_hash=leaf.hex(),
        details=details,
    )
    db.add(record)
    return record