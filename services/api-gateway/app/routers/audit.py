"""Audit log search + Merkle proof + CSV export (Phase 7.4, FR-AUDIT-01).

GET /v1/audit/records                      search (auditor and above)
GET /v1/audit/records/{id}/proof           Merkle proof bundle for one record
GET /v1/audit/export                       CSV export of a filtered query

Proofs are rebuilt from the stored `event_hash` leaves of the record's batch,
so verification needs no volatile state: leaf -> root via sibling steps,
checked against the on-chain-anchored `anchor_batches.merkle_root`.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from app.deps import require_auditor_or_above
from at_shared.db import get_db
from at_shared.merkle import merkle_proof, verify_proof
from at_shared.models import AnchorBatch, AuditRecord
from at_shared.schemas.audit import (
    AuditRecordRead,
    AuditSearchResult,
    MerkleProofBundle,
    MerkleProofStep,
)
from at_shared.schemas.auth import CurrentUser
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/audit", tags=["audit"])

_VALID_DECISIONS = {"approve", "reject", "escalate"}


def _build_query(db: Session, org_id: str, *, agent_id, event_type, from_dt, to_dt):
    stmt = select(AuditRecord).where(AuditRecord.org_id == org_id)
    if agent_id:
        stmt = stmt.where(AuditRecord.agent_id == agent_id)
    if event_type:
        stmt = stmt.where(AuditRecord.event_type == event_type)
    if from_dt:
        stmt = stmt.where(AuditRecord.created_at >= from_dt)
    if to_dt:
        stmt = stmt.where(AuditRecord.created_at <= to_dt)
    return stmt


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


@router.get("/records", response_model=AuditSearchResult)
def search_records(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
    agent_id: str | None = None,
    event_type: str | None = Query(default=None, pattern=r"^(decision|policy_update)$"),
    decision: str | None = Query(default=None, pattern=r"^(approve|reject|escalate)$"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    anchored: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditSearchResult:
    from_ts = _parse_dt(from_.isoformat()) if from_ else None
    to_ts = _parse_dt(to.isoformat()) if to else None
    stmt = _build_query(db, user.org_id, agent_id=agent_id, event_type=event_type, from_dt=from_ts, to_dt=to_ts)
    if decision:
        stmt = stmt.where(AuditRecord.details["decision"].as_string() == decision)
    if anchored is not None:
        stmt = (
            stmt.where(AuditRecord.anchored_batch_id.is_not(None))
            if anchored
            else stmt.where(AuditRecord.anchored_batch_id.is_(None))
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(AuditRecord.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return AuditSearchResult(
        items=[AuditRecordRead.model_validate(r) for r in rows],
        total=total or 0,
    )


@router.get("/records/{record_id}/proof", response_model=MerkleProofBundle)
def record_proof(
    record_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
) -> MerkleProofBundle:
    record = db.scalar(
        select(AuditRecord).where(AuditRecord.id == record_id, AuditRecord.org_id == user.org_id)
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit record not found")
    if record.anchored_batch_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Record is not anchored yet; proof becomes available after the next batch",
        )

    batch = db.scalar(
        select(AnchorBatch).where(AnchorBatch.batch_id == record.anchored_batch_id)
    )
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anchor batch not found")

    siblings = db.scalars(
        select(AuditRecord.event_hash)
        .where(AuditRecord.anchored_batch_id == record.anchored_batch_id)
        .order_by(AuditRecord.created_at.asc(), AuditRecord.id.asc())
    ).all()
    leaves = [bytes.fromhex(h) for h in siblings]
    index = next(i for i, h in enumerate(siblings) if h == record.event_hash)

    leaf = bytes.fromhex(record.event_hash)
    root = bytes.fromhex(batch.merkle_root)
    proof = merkle_proof(leaves, index)
    verified = verify_proof(leaf, proof, root, index)

    return MerkleProofBundle(
        record_id=record.id,
        leaf=record.event_hash,
        root=batch.merkle_root,
        batch_id=batch.batch_id,
        anchored_at=batch.anchored_at or batch.created_at,
        proof=[MerkleProofStep(hash=s.hex(), is_right=right) for s, right in proof],
        verified=verified,
    )


@router.get("/export", response_class=StreamingResponse)
def export_csv(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
    agent_id: str | None = None,
    event_type: str | None = Query(default=None, pattern=r"^(decision|policy_update)$"),
    decision: str | None = Query(default=None, pattern=r"^(approve|reject|escalate)$"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> StreamingResponse:
    from_ts = _parse_dt(from_.isoformat()) if from_ else None
    to_ts = _parse_dt(to.isoformat()) if to else None
    stmt = _build_query(db, user.org_id, agent_id=agent_id, event_type=event_type, from_dt=from_ts, to_dt=to_ts)
    if decision:
        stmt = stmt.where(AuditRecord.details["decision"].as_string() == decision)
    rows = db.scalars(stmt.order_by(AuditRecord.created_at.asc())).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["id", "created_at", "event_type", "agent_id", "transaction_id",
         "decision", "to_address", "value_wei", "event_hash", "anchored_batch_id"]
    )
    for r in rows:
        details = r.details or {}
        writer.writerow(
            [
                r.id,
                r.created_at.isoformat(),
                r.event_type,
                r.agent_id,
                details.get("transaction_id", ""),
                details.get("decision", ""),
                details.get("to_address", ""),
                details.get("value_wei", ""),
                r.event_hash,
                r.anchored_batch_id if r.anchored_batch_id is not None else "",
            ]
        )
    data = buf.getvalue()
    headers = {"Content-Disposition": 'attachment; filename="audit_export.csv"'}
    return StreamingResponse(iter([data]), media_type="text/csv", headers=headers)


@router.get("/export.pdf", response_class=Response)
def export_pdf(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_auditor_or_above),
    agent_id: str | None = None,
    event_type: str | None = Query(default=None, pattern=r"^(decision|policy_update)$"),
    decision: str | None = Query(default=None, pattern=r"^(approve|reject|escalate)$"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> Response:
    """PDF audit export including the Merkle proof bundle for anchored records.

    The export is self-contained: every anchored record carries its leaf,
    anchored root, batch id, and sibling steps, so an auditor can independently
    recompute the root off-line (FR-AUDIT-01 tamper detection).
    """
    from_ts = _parse_dt(from_.isoformat()) if from_ else None
    to_ts = _parse_dt(to.isoformat()) if to else None
    stmt = _build_query(db, user.org_id, agent_id=agent_id, event_type=event_type, from_dt=from_ts, to_dt=to_ts)
    if decision:
        stmt = stmt.where(AuditRecord.details["decision"].as_string() == decision)
    rows = db.scalars(
        stmt.order_by(AuditRecord.created_at.asc()).limit(500)
    ).all()

    # Batch proofs: group anchored records by batch, rebuild each tree.
    batches: dict[int, AnchorBatch] = {
        b.batch_id: b
        for b in db.scalars(
            select(AnchorBatch).where(AnchorBatch.batch_id.in_(
                {r.anchored_batch_id for r in rows if r.anchored_batch_id is not None} or [-1]
            ))
        )
    }
    leaves_by_batch: dict[int, list[tuple[str, bytes]]] = {}
    for r in rows:
        if r.anchored_batch_id is None:
            continue
        leaves_by_batch.setdefault(r.anchored_batch_id, []).append((r.id, bytes.fromhex(r.event_hash)))

    pdf = _render_pdf(user, rows, batches, leaves_by_batch, decision=decision, event_type=event_type)
    headers = {"Content-Disposition": 'attachment; filename="audit_export.pdf"'}
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers=headers,
    )


def _render_pdf(
    user: CurrentUser,
    rows: list[AuditRecord],
    batches: dict[int, AnchorBatch],
    leaves_by_batch: dict[int, list[tuple[str, bytes]]],
    *,
    decision: str | None,
    event_type: str | None,
) -> bytes:
    """Render the audit export PDF via reportlab (imported lazily)."""
    from io import BytesIO

    from at_shared.merkle import merkle_proof
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    mono = ParagraphStyle(
        "mono",
        parent=styles["Code"],
        fontSize=6,
        leading=8,
        textColor=colors.black,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    story = [
        Paragraph("AgentThreshold — Audit Export", styles["Title"]),
        Spacer(1, 4),
        Paragraph(
            f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')} "
            f"by {user.email} (role {user.role}) · org {user.org_id}",
            styles["Normal"],
        ),
        Paragraph(
            f"Filters: decision={decision or 'all'} · event_type={event_type or 'all'} · "
            f"{len(rows)} records (max 500)",
            styles["Normal"],
        ),
        Spacer(1, 8),
    ]

    head = ["Time (UTC)", "Event", "Agent", "Decision", "Value (wei)", "Batch"]
    table_rows = [head]
    for r in rows:
        details = r.details or {}
        table_rows.append(
            [
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.event_type,
                r.agent_id[:10],
                str(details.get("decision", "")),
                str(details.get("value_wei", "")),
                str(r.anchored_batch_id or "pending"),
            ]
        )
    data_table = Table(table_rows, repeatRows=1)
    data_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(data_table)
    story.append(Spacer(1, 8))

    # Merkle proof appendix: self-contained, per anchored record.
    anchored = [r for r in rows if r.anchored_batch_id is not None]
    if anchored:
        story.append(Paragraph("Merkle proof bundle (FR-AUDIT-01)", styles["Heading2"]))
        for r in anchored:
            batch = batches.get(r.anchored_batch_id)
            leaves = leaves_by_batch.get(r.anchored_batch_id, [])
            index = next((i for i, (rid, _) in enumerate(leaves) if rid == r.id), -1)
            proof: list[tuple[bytes, bool]] = []
            if index >= 0 and batch is not None:
                proof = merkle_proof([leaf for _, leaf in leaves], index)
            steps = "  |  ".join(
                f"{'R' if right else 'L'}:{s.hex()}" for s, right in proof
            )
            story.append(
                Paragraph(
                    f"<b>record {r.id}</b> — batch #{r.anchored_batch_id}"
                    f" (root {batch.merkle_root if batch else 'unknown'})<br/>"
                    f"leaf {r.event_hash}<br/>"
                    f"proof {steps or 'unavailable'}",
                    mono,
                )
            )
            story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()