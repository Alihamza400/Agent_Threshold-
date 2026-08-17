import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import { hasRole, useAuth } from "../auth/AuthContext";
import type { Policy, PolicyUpdate } from "../api/types";

export function Policies() {
  const { user } = useAuth();
  const canEdit = hasRole(user, ["admin"]);
  const { data: agents } = useQuery({ queryKey: ["agents"], queryFn: api.listAgents, retry: false });
  const [agentId, setAgentId] = useState<string>("");

  useEffect(() => {
    if (!agentId && agents?.length) setAgentId(agents[0].id);
  }, [agents, agentId]);

  const changes = useQuery({
    queryKey: ["policy-changes"],
    queryFn: () => api.searchAudit({ eventType: "policy_update", limit: 15 }),
    refetchInterval: 60_000,
  });

  return (
    <div>
      <h2>Policies</h2>
      <p className="muted">
        Per-agent, versioned policies. Every change publishes a new immutable
        version and is written to the audit log (FR-POL-02).
      </p>
      <label>
        Agent
        <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          <option value="">Select agent…</option>
          {(agents ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.wallet_address.slice(0, 10)}…)
            </option>
          ))}
        </select>
      </label>

      {agentId && <PolicyViewer key={agentId} agentId={agentId} canEdit={canEdit} />}

      <section className="panel">
        <h3>Recent policy changes (org-wide)</h3>
        {changes.isLoading ? (
          <div className="muted">Loading…</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Changed by</th>
                <th>Version</th>
                <th>Change note</th>
              </tr>
            </thead>
            <tbody>
              {(changes.data?.items ?? []).map((r) => {
                const d = r.details;
                return (
                  <tr key={r.id}>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                    <td className="mono">
                      {String(d.actor_email ?? d.actor_id ?? "unknown")}
                    </td>
                    <td className="mono">
                      v{String(d.from_version ?? "?")} → v{String(d.to_version ?? "?")}
                    </td>
                    <td>{String(d.change_note ?? "—")}</td>
                  </tr>
                );
              })}
              {(changes.data?.items ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    No policy changes yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function PolicyViewer({ agentId, canEdit }: { agentId: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const policyQ = useQuery({
    queryKey: ["policy", agentId],
    queryFn: () => api.getPolicy(agentId),
    enabled: Boolean(agentId),
  });
  const versionsQ = useQuery({
    queryKey: ["policy-versions", agentId],
    queryFn: () => api.listPolicyVersions(agentId),
    enabled: Boolean(agentId),
  });

  const [form, setForm] = useState<PolicyUpdate>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const update = useMutation({
    mutationFn: () => api.updatePolicy(agentId, form),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["policy", agentId] });
      qc.invalidateQueries({ queryKey: ["policy-versions", agentId] });
      setDone(`Published version ${p.version}`);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Update failed"),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    update.mutate();
  }

  if (policyQ.isLoading) return <div className="muted">Loading policy…</div>;
  const policy = policyQ.data;
  if (!policy) return <div className="alert">No active policy found.</div>;

  const field = (name: keyof PolicyUpdate) =>
    form[name] !== undefined ? form[name] : policy[name as keyof Policy];

  return (
    <>
      <section className="panel">
        <h3>
          Active policy — v{policy.version}
          {canEdit ? "" : " (read-only for auditors)"}
        </h3>
        {canEdit ? (
          <form className="policy-form" onSubmit={onSubmit}>
            <label>
              Per-tx spend limit (USD)
              <input
                type="number"
                step="0.01"
                value={String(field("spend_limit_usd") ?? "")}
                onChange={(e) =>
                  setForm((f) => ({ ...f, spend_limit_usd: e.target.value ? Number(e.target.value) : null }))
                }
              />
            </label>
            <label>
              Daily spend limit (USD)
              <input
                type="number"
                step="0.01"
                value={String(field("daily_spend_limit_usd") ?? "")}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    daily_spend_limit_usd: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </label>
            <label>
              Rate limit (per minute)
              <input
                type="number"
                value={String(field("rate_limit_per_minute") ?? "")}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    rate_limit_per_minute: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </label>
            <label>
              Gas ceiling (wei)
              <input
                type="number"
                value={String(field("gas_ceiling") ?? "")}
                onChange={(e) =>
                  setForm((f) => ({ ...f, gas_ceiling: e.target.value ? Number(e.target.value) : null }))
                }
              />
            </label>
            <label>
              Anomaly threshold (0–100)
              <input
                type="number"
                min={0}
                max={100}
                value={String(field("anomaly_threshold"))}
                onChange={(e) => setForm((f) => ({ ...f, anomaly_threshold: Number(e.target.value) }))}
              />
            </label>
            <label>
              Active window start (UTC minutes)
              <input
                type="number"
                min={0}
                max={1439}
                value={String(field("active_from_minute") ?? "")}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    active_from_minute: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </label>
            <label>
              Active window end (UTC minutes)
              <input
                type="number"
                min={0}
                max={1439}
                value={String(field("active_to_minute") ?? "")}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    active_to_minute: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              />
            </label>
            <label className="wide">
              Change note
              <input
                value={(form.change_note as string) ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, change_note: e.target.value }))}
                placeholder="Why this change (audit trail)"
              />
            </label>
            {error && <div className="alert alert-error">{error}</div>}
            {done && <div className="alert alert-ok">{done}</div>}
            <button className="btn btn-primary" disabled={update.isPending}>
              {update.isPending ? "Publishing…" : "Publish new version"}
            </button>
          </form>
        ) : (
          <table>
            <tbody>
              {Object.entries(policy)
                .filter(([k]) => k !== "agent_id" && k !== "created_at" && k !== "created_by")
                .map(([k, v]) => (
                  <tr key={k}>
                    <td className="muted">{k}</td>
                    <td className="mono">{Array.isArray(v) ? v.join(", ") : String(v)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h3>Version history</h3>
        <table>
          <thead>
            <tr>
              <th>Version</th>
              <th>Active</th>
              <th>Created by</th>
              <th>Created at</th>
            </tr>
          </thead>
          <tbody>
            {(versionsQ.data ?? []).map((v: Policy) => (
              <tr key={v.version}>
                <td>v{v.version}</td>
                <td>{v.is_active ? "Yes" : "No"}</td>
                <td className="mono">{v.created_by.slice(0, 8)}…</td>
                <td>{new Date(v.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}