import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import { hasRole, useAuth } from "../auth/AuthContext";

interface HaltTarget {
  scope: "agent" | "org";
  agentId?: string;
  agentName?: string;
}

export function Agents() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = hasRole(user, ["admin"]);
  const { data: agents, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: api.listAgents,
  });
  const [name, setName] = useState("");
  const [wallet, setWallet] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<HaltTarget | null>(null);
  const [reason, setReason] = useState("");
  const [haltError, setHaltError] = useState<string | null>(null);

  const register = useMutation({
    mutationFn: () => api.registerAgent(name, wallet),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      setName("");
      setWallet("");
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Registration failed"),
  });

  const halt = useMutation({
    mutationFn: ({ target, reason }: { target: HaltTarget; reason: string }) =>
      api.killSwitch(target.scope, target.agentId, reason || "admin action"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      setTarget(null);
      setReason("");
      setHaltError(null);
    },
    onError: (err) =>
      setHaltError(err instanceof Error ? err.message : "Kill-switch failed"),
  });

  const resume = useMutation({
    mutationFn: ({ scope, agentId }: { scope: "agent" | "org"; agentId?: string }) =>
      api.resumeKillSwitch(scope, agentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    register.mutate();
  }

  const orgHalted = (agents ?? []).length > 0 && (agents ?? []).every((a) => a.halted);

  return (
    <div>
      <h2>Agents</h2>
      <p className="muted">
        Register agent wallets and control the kill-switch. A halted agent is
        fail-closed: every screening request is rejected. Halting the whole org
        stops all agents at once.
      </p>

      <section className="panel">
        <h3>Register agent</h3>
        <form className="row-form" onSubmit={onSubmit}>
          <input
            placeholder="Agent name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            placeholder="0x wallet address (42 chars)"
            value={wallet}
            onChange={(e) => setWallet(e.target.value)}
            minLength={42}
            maxLength={42}
            required
            className="mono"
          />
          <button className="btn btn-primary" disabled={register.isPending}>
            {register.isPending ? "Registering…" : "Register"}
          </button>
        </form>
        {error && <div className="alert alert-error">{error}</div>}
      </section>

      {isAdmin && (
        <section className="panel">
          <h3>Org-wide kill-switch</h3>
          <p className="muted small">
            Instantly fail-closed for every agent in the org (FR-ADMIN-02).
            Requires an explicit confirm with a reason.
          </p>
          <button
            className="btn btn-danger"
            disabled={orgHalted}
            onClick={() => {
              setHaltError(null);
              setTarget({ scope: "org" });
            }}
          >
            Halt entire org
          </button>{" "}
          {orgHalted && (
            <button
              className="btn btn-ghost"
              disabled={resume.isPending}
              onClick={() => resume.mutate({ scope: "org" })}
            >
              Resume org
            </button>
          )}
          {haltError && <div className="alert alert-error">{haltError}</div>}
        </section>
      )}

      <section className="panel">
        <h3>Agent list</h3>
        {isLoading ? (
          <div className="muted">Loading…</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Wallet</th>
                <th>Status</th>
                <th>Halted</th>
                <th>Reason</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(agents ?? []).map((a) => (
                <tr key={a.id}>
                  <td>{a.name}</td>
                  <td className="mono">{a.wallet_address}</td>
                  <td>
                    <span className={`badge badge-${a.status}`}>{a.status}</span>
                  </td>
                  <td>{a.halted ? "Yes" : "No"}</td>
                  <td>{a.halt_reason ?? "—"}</td>
                  <td>
                    {a.halted ? (
                      <button
                        className="btn btn-ghost"
                        onClick={() => resume.mutate({ scope: "agent", agentId: a.id })}
                        disabled={resume.isPending}
                      >
                        Resume
                      </button>
                    ) : (
                      <button
                        className="btn btn-danger"
                        onClick={() => {
                          setHaltError(null);
                          setTarget({ scope: "agent", agentId: a.id, agentName: a.name });
                        }}
                        disabled={halt.isPending}
                      >
                        Halt
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(agents ?? []).length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    No agents registered.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </section>

      {target && (
        <div className="modal-backdrop" onClick={() => setTarget(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Confirm kill-switch</h3>
            <p>
              {target.scope === "org"
                ? "This halts EVERY agent in the org. All screening will fail-closed until resumed."
                : `This halts "${target.agentName}". All screening for this agent will fail-closed until resumed.`}
            </p>
            <label>
              Reason (recorded in audit trail)
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. compromised key, policy incident…"
                rows={2}
              />
            </label>
            {haltError && <div className="alert alert-error">{haltError}</div>}
            <div className="row-form">
              <button
                className="btn btn-danger"
                disabled={halt.isPending}
                onClick={() => halt.mutate({ target, reason })}
              >
                {halt.isPending ? "Halting…" : "Confirm halt"}
              </button>
              <button className="btn btn-ghost" onClick={() => setTarget(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}