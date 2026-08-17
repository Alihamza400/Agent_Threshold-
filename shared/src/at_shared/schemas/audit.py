"""Audit log search/export schemas (Phase 7.4 — FR-AUDIT-01)."""

from __future__ import annotations

from datetime import datetime

from at_shared.schemas.common import OrmModel


class AuditRecordRead(OrmModel):
    id: str
    org_id: str
    agent_id: str
    event_type: str
    event_hash: str
    details: dict
    anchored_batch_id: int | None = None
    created_at: datetime


class AuditSearchResult(OrmModel):
    items: list[AuditRecordRead]
    total: int


class MerkleProofStep(OrmModel):
    hash: str
    is_right: bool


class MerkleProofBundle(OrmModel):
    """A record's recoverable on-chain proof: leaf -> root via sibling steps."""

    record_id: str
    leaf: str
    root: str
    batch_id: int
    anchored_at: datetime
    proof: list[MerkleProofStep]
    verified: bool