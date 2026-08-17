import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

const TABS = ["pending", "approved", "rejected", "expired"] as const;

export function Approvals() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number]>("pending");
  const { data: items, isLoading } = useQuery({
    queryKey: ["approvals", tab],
    queryFn: () => api.listApprovals(tab),
  });

  const decide = useMutation({
    mutationFn: ({ id, action, note }: { id: string; action: "approve" | "reject"; note: string }) =>
      api.decideApproval(id, action, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });

  return (
    <div>
      <h2>Approval queue</h2>
      <p className="muted">
        Escalated decisions need a human. An overdue pending escalation expires
        to rejected (fail-closed). Double decisions are rejected by the API.
      </p>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={t === tab ? "tab active" : "tab"}
            onClick={() => setTab(t)}
          >
            {t}
            {t === "pending" && items ? ` (${items.length})` : ""}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="muted">Loading…</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>To</th>
              <th>Value (wei)</th>
              <th>Risk</th>
              <th>Status</th>
              <th>Decided</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {(items ?? []).map((a) => (
              <tr key={a.id}>
                <td>{new Date(a.created_at).toLocaleString()}</td>
                <td>{a.agent_name}</td>
                <td className="mono">{(a.to_address ?? "").slice(0, 12)}…</td>
                <td className="mono">{a.value_wei.toLocaleString()}</td>
                <td title={a.risk_summary ?? ""}>
                  <span className="badge badge-escalate">{a.decision}</span>
                  <div className="muted small">{a.risk_summary?.slice(0, 60) ?? ""}</div>
                </td>
                <td>
                  <span className={`badge badge-${a.status}`}>{a.status}</span>
                </td>
                <td className="muted small">
                  {a.decided_at ? new Date(a.decided_at).toLocaleString() : "—"}
                </td>
                <td>
                  {a.status === "pending" ? (
                    <span className="row">
                      <DecideButton
                        label="Approve"
                        tone="ok"
                        busy={decide.isPending}
                        onClick={(note) => decide.mutate({ id: a.id, action: "approve", note })}
                      />
                      <DecideButton
                        label="Reject"
                        tone="danger"
                        busy={decide.isPending}
                        onClick={(note) => decide.mutate({ id: a.id, action: "reject", note })}
                      />
                    </span>
                  ) : (
                    <span className="muted small">{a.decision_note ?? "—"}</span>
                  )}
                </td>
              </tr>
            ))}
            {(items ?? []).length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  Nothing in this queue.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DecideButton({
  label,
  tone,
  busy,
  onClick,
}: {
  label: string;
  tone: "ok" | "danger";
  busy: boolean;
  onClick: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <form
      className="row-form inline"
      onSubmit={(e) => {
        e.preventDefault();
        onClick(note);
      }}
    >
      <input
        className="small"
        placeholder="note (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={500}
      />
      <button className={`btn btn-${tone}`} disabled={busy}>
        {label}
      </button>
    </form>
  );
}