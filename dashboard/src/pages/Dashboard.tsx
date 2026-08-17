import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth, hasRole } from "../auth/AuthContext";

function useRoleAware<T>(enabled: boolean, key: string[], fn: () => Promise<T>) {
  return useQuery({
    queryKey: key,
    queryFn: fn,
    enabled,
    retry: false,
    refetchInterval: 30_000,
  });
}

export function Dashboard() {
  const { user } = useAuth();
  const canReview = hasRole(user, ["admin", "approver"]);

  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: api.metricsOverview,
    refetchInterval: 30_000,
  });

  const approvals = useRoleAware(
    canReview,
    ["approvals-pending"],
    () => api.listApprovals("pending")
  );

  const txs = useQuery({
    queryKey: ["txn-dashboard"],
    queryFn: () => api.listTransactions({ limit: 10 }),
  });

  const m = metrics.data;
  const pendingCount = canReview ? approvals.data?.length : null;

  return (
    <div>
      <h2>Dashboard</h2>
      <p className="muted">
        Real-time posture for your agents. Decisions are immutable and anchored
        on-chain via Merkle batches.
      </p>

      <div className="grid-4">
        <Stat
          label="Screened (24h)"
          value={m ? String(m.total_transactions_24h) : "—"}
          sub={m ? `${m.window_hours}h window` : "loading"}
        />
        <Stat
          label="p95 latency"
          value={m && m.latency_ms.p95 != null ? `${m.latency_ms.p95} ms` : "—"}
          sub="SLO target < 2000 ms"
        />
        <Stat
          label="Fail-closed rate"
          value={m ? `${(m.fail_closed_rate * 100).toFixed(1)}%` : "—"}
          sub="reject + escalate / all"
        />
        <Stat
          label="Pending approvals"
          value={canReview ? String(pendingCount ?? "—") : "—"}
          sub={canReview ? "awaiting human review" : "no access"}
        />
      </div>

      <div className="grid-2">
        <section className="panel">
          <h3>Decision mix (24h)</h3>
          {metrics.isLoading ? (
            <div className="muted">Loading…</div>
          ) : (
            <div className="bar-chart">
              {(["approve", "reject", "escalate"] as const).map((d) => (
                <div key={d} className="bar-row">
                  <span className="bar-label">{d}</span>
                  <div className="bar-track">
                    <div
                      className={`bar-fill bar-${d}`}
                      style={{
                        width: `${m && m.total_transactions_24h ? Math.max((m.decision_mix[d] / m.total_transactions_24h) * 100, 0) : 0}%`,
                      }}
                    />
                  </div>
                  <span className="bar-value">{m?.decision_mix[d] ?? 0}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <h3>Screening volume — last 14 days</h3>
          {m && m.daily_series.counts.some((c) => c > 0) ? (
            <div className="mini-bars" title={m.daily_series.days.join(", ")}>
              {m.daily_series.counts.map((c, i) => (
                <div
                  key={i}
                  className="mini-bar"
                  style={{ height: `${Math.max((c / Math.max(...m.daily_series.counts)) * 100, 4)}%` }}
                  title={`${m.daily_series.days[i]}: ${c}`}
                />
              ))}
            </div>
          ) : (
            <div className="muted">No volume yet — screen a transaction to see the trend.</div>
          )}
          <p className="muted small">
            Approvals pending: {m?.approvals.pending ?? "—"} · avg decision time:{" "}
            {m?.approvals.avg_decision_hours != null ? `${m.approvals.avg_decision_hours}h` : "—"}
          </p>
        </section>
      </div>

      <section className="panel">
        <h3>Recent decisions</h3>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>To</th>
              <th>Value (wei)</th>
              <th>Latency</th>
              <th>Decision</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(txs.data ?? []).map((t) => (
              <tr key={t.id}>
                <td>{new Date(t.created_at).toLocaleString()}</td>
                <td>{t.agent_id.slice(0, 8)}…</td>
                <td className="mono">{(t.to_address ?? "").slice(0, 10)}…</td>
                <td className="mono">{t.value_wei.toLocaleString()}</td>
                <td>{t.screened_ms != null ? `${t.screened_ms} ms` : "—"}</td>
                <td>
                  <span className={`badge badge-${t.decision}`}>{t.decision}</span>
                </td>
                <td>{t.status}</td>
              </tr>
            ))}
            {!txs.isLoading && (txs.data ?? []).length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No transactions yet. Screen one via the SDK to see it here.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="panel stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      <div className="muted small">{sub}</div>
    </div>
  );
}