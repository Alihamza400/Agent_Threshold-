import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

const DECISIONS = ["", "approve", "reject", "escalate"] as const;

export function Transactions() {
  const [agentId, setAgentId] = useState("");
  const [decision, setDecision] = useState<(typeof DECISIONS)[number]>("");
  const { data: agents } = useQuery({ queryKey: ["agents"], queryFn: api.listAgents, retry: false });

  const txs = useQuery({
    queryKey: ["transactions", agentId, decision],
    queryFn: () =>
      api.listTransactions({
        agentId: agentId || undefined,
        decision: decision || undefined,
        limit: 100,
      }),
  });

  return (
    <div>
      <h2>Transactions</h2>
      <p className="muted">Org-wide screening history (auditor and above).</p>

      <div className="row-form">
        <label>
          Agent
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">All agents</option>
            {(agents ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Decision
          <select value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)}>
            {DECISIONS.map((d) => (
              <option key={d} value={d}>
                {d === "" ? "All" : d}
              </option>
            ))}
          </select>
        </label>
      </div>

      {txs.isLoading ? (
        <div className="muted">Loading…</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>From</th>
              <th>To</th>
              <th>Value (wei)</th>
              <th>Decision</th>
              <th>Status</th>
              <th>Policy v</th>
            </tr>
          </thead>
          <tbody>
            {(txs.data ?? []).map((t) => (
              <tr key={t.id}>
                <td>{new Date(t.created_at).toLocaleString()}</td>
                <td>{t.agent_id.slice(0, 8)}…</td>
                <td className="mono">{t.from_address.slice(0, 10)}…</td>
                <td className="mono">{(t.to_address ?? "").slice(0, 10)}…</td>
                <td className="mono">{t.value_wei.toLocaleString()}</td>
                <td>
                  <span className={`badge badge-${t.decision}`}>{t.decision}</span>
                </td>
                <td>{t.status}</td>
                <td>{t.policy_version ?? "—"}</td>
              </tr>
            ))}
            {(txs.data ?? []).length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No transactions match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}