import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, downloadAuditExport } from "../api/client";
import type { MerkleProofBundle } from "../api/types";

interface Filters {
  eventType: string;
  decision: string;
  anchored: string;
}

export function AuditLog() {
  const [filters, setFilters] = useState<Filters>({ eventType: "", decision: "", anchored: "" });
  const [proof, setProof] = useState<MerkleProofBundle | null>(null);
  const [exporting, setExporting] = useState(false);

  const search = useQuery({
    queryKey: ["audit", filters],
    queryFn: () =>
      api.searchAudit({
        eventType: filters.eventType || undefined,
        decision: filters.decision || undefined,
        anchored: filters.anchored ? filters.anchored === "true" : undefined,
        limit: 100,
      }),
  });

  async function doExport() {
    setExporting(true);
    try {
      const csv = await api.auditExport({
        eventType: filters.eventType || undefined,
        decision: filters.decision || undefined,
      });
      downloadAuditExport(csv);
    } finally {
      setExporting(false);
    }
  }

  async function doExportPdf() {
    setExporting(true);
    try {
      const blob = await api.auditExportPdf({
        eventType: filters.eventType || undefined,
        decision: filters.decision || undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "audit_export.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  async function showProof(recordId: string) {
    try {
      setProof(await api.auditProof(recordId));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Proof unavailable");
    }
  }

  return (
    <div>
      <h2>Audit log</h2>
      <p className="muted">
        Immutable decision & policy-change records. Each batch is Merkle-anchored
        on-chain; every record has a verifiable proof bundle (FR-AUDIT-01).
      </p>

      <div className="row-form">
        <label>
          Event type
          <select
            value={filters.eventType}
            onChange={(e) => setFilters((f) => ({ ...f, eventType: e.target.value }))}
          >
            <option value="">All</option>
            <option value="decision">decision</option>
            <option value="policy_update">policy_update</option>
          </select>
        </label>
        <label>
          Decision
          <select
            value={filters.decision}
            onChange={(e) => setFilters((f) => ({ ...f, decision: e.target.value }))}
          >
            <option value="">All</option>
            <option value="approve">approve</option>
            <option value="reject">reject</option>
            <option value="escalate">escalate</option>
          </select>
        </label>
        <label>
          Anchored
          <select
            value={filters.anchored}
            onChange={(e) => setFilters((f) => ({ ...f, anchored: e.target.value }))}
          >
            <option value="">All</option>
            <option value="true">Anchored</option>
            <option value="false">Pending</option>
          </select>
        </label>
        <button className="btn" onClick={doExport} disabled={exporting}>
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
        <button className="btn" onClick={doExportPdf} disabled={exporting}>
          Export PDF (proof bundle)
        </button>
      </div>

      {search.isLoading ? (
        <div className="muted">Loading…</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Agent</th>
              <th>Decision</th>
              <th>Value (wei)</th>
              <th>Batch</th>
              <th>Proof</th>
            </tr>
          </thead>
          <tbody>
            {(search.data?.items ?? []).map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>
                  <span className="badge">{r.event_type}</span>
                </td>
                <td className="mono">{r.agent_id.slice(0, 8)}…</td>
                <td>{String(r.details.decision ?? "")}</td>
                <td className="mono">{String(r.details.value_wei ?? "")}</td>
                <td>{r.anchored_batch_id ? `#${r.anchored_batch_id}` : "pending"}</td>
                <td>
                  {r.anchored_batch_id ? (
                    <button className="btn btn-ghost small" onClick={() => showProof(r.id)}>
                      Verify
                    </button>
                  ) : (
                    <span className="muted small">not anchored</span>
                  )}
                </td>
              </tr>
            ))}
            {(search.data?.items ?? []).length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No audit records match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <p className="muted small">Total matching: {search.data?.total ?? 0}</p>

      {proof && <ProofModal proof={proof} onClose={() => setProof(null)} />}
    </div>
  );
}

function ProofModal({ proof, onClose }: { proof: MerkleProofBundle; onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>
          Merkle proof {proof.verified ? <span className="badge badge-ok">verified</span> : <span className="badge badge-reject">mismatch</span>}
        </h3>
        <p className="muted small">
          Batch #{proof.batch_id} · anchored {new Date(proof.anchored_at).toLocaleString()}
        </p>
        <dl>
          <dt>Leaf</dt>
          <dd className="mono small">{proof.leaf}</dd>
          <dt>Root</dt>
          <dd className="mono small">{proof.root}</dd>
        </dl>
        <h4>Sibling steps</h4>
        <ol className="mono small">
          {proof.proof.map((p, i) => (
            <li key={i}>
              [{p.is_right ? "right" : "left"}] {p.hash}
            </li>
          ))}
        </ol>
        <button className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}