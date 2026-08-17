// Thin fetch wrapper: JWT auth, auto-refresh, org-scoped rate-limit header.
import type {
  Agent,
  AgentRegistered,
  Approval,
  AuditSearchResult,
  CurrentUser,
  MerkleProofBundle,
  MetricsOverview,
  Policy,
  PolicyUpdate,
  TokenResponse,
  Transaction,
} from "./types";

const ACCESS_KEY = "at_access_token";
const REFRESH_KEY = "at_refresh_token";
const ORG_KEY = "at_org_id";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export function saveTokens(tokens: TokenResponse, orgId: string): void {
  localStorage.setItem(ACCESS_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  localStorage.setItem(ORG_KEY, orgId);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(ORG_KEY);
}

export function isAuthenticated(): boolean {
  return Boolean(localStorage.getItem(ACCESS_KEY));
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retried = false
): Promise<T> {
  const access = localStorage.getItem(ACCESS_KEY);
  const orgId = localStorage.getItem(ORG_KEY);
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (access) headers.Authorization = `Bearer ${access}`;
  if (orgId) headers["x-org-id"] = orgId;

  const resp = await fetch(`/v1${path}`, { ...options, headers });

  if (resp.status === 401 && access && !retried) {
    const refreshed = await tryRefresh();
    if (refreshed) return request<T>(path, options, true);
  }
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

async function requestText(path: string, options: RequestInit = {}, retried = false): Promise<string> {
  const access = localStorage.getItem(ACCESS_KEY);
  const orgId = localStorage.getItem(ORG_KEY);
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };
  if (access) headers.Authorization = `Bearer ${access}`;
  if (orgId) headers["x-org-id"] = orgId;

  const resp = await fetch(`/v1${path}`, { ...options, headers });
  if (resp.status === 401 && access && !retried) {
    const refreshed = await tryRefresh();
    if (refreshed) return requestText(path, options, true);
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, `${resp.status} ${resp.statusText}`);
  }
  return resp.text();
}

async function requestBlob(
  path: string,
  options: RequestInit = {},
  retried = false
): Promise<Blob> {
  const access = localStorage.getItem(ACCESS_KEY);
  const orgId = localStorage.getItem(ORG_KEY);
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };
  if (access) headers.Authorization = `Bearer ${access}`;
  if (orgId) headers["x-org-id"] = orgId;

  const resp = await fetch(`/v1${path}`, { ...options, headers });
  if (resp.status === 401 && access && !retried) {
    const refreshed = await tryRefresh();
    if (refreshed) return requestBlob(path, options, true);
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, `${resp.status} ${resp.statusText}`);
  }
  return resp.blob();
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return false;
  try {
    const resp = await fetch("/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!resp.ok) {
      clearTokens();
      return false;
    }
    const tokens = (await resp.json()) as TokenResponse;
    const org = localStorage.getItem(ORG_KEY) ?? "";
    saveTokens(tokens, org);
    return true;
  } catch {
    return false;
  }
}

export const api = {
  login(email: string, password: string): Promise<TokenResponse> {
    return request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },
  me(): Promise<CurrentUser> {
    return request<CurrentUser>("/auth/me");
  },

  listAgents(): Promise<Agent[]> {
    return request<Agent[]>("/agents");
  },
  registerAgent(name: string, walletAddress: string): Promise<AgentRegistered> {
    return request<AgentRegistered>("/agents/register", {
      method: "POST",
      body: JSON.stringify({ name, wallet_address: walletAddress }),
    });
  },
  getPolicy(agentId: string): Promise<Policy> {
    return request<Policy>(`/agents/${agentId}/policy`);
  },
  listPolicyVersions(agentId: string): Promise<Policy[]> {
    return request<Policy[]>(`/agents/${agentId}/policy/versions`);
  },
  updatePolicy(agentId: string, update: PolicyUpdate): Promise<Policy> {
    return request<Policy>(`/agents/${agentId}/policy`, {
      method: "PUT",
      body: JSON.stringify(update),
    });
  },

  listApprovals(status = "pending", agentId?: string): Promise<Approval[]> {
    const qs = new URLSearchParams({ status });
    if (agentId) qs.set("agent_id", agentId);
    return request<Approval[]>(`/approvals?${qs.toString()}`);
  },
  decideApproval(id: string, action: "approve" | "reject", note?: string): Promise<Approval> {
    return request<Approval>(`/approvals/${id}/${action}`, {
      method: "POST",
      body: JSON.stringify({ note: note ?? null }),
    });
  },

  searchAudit(params: {
    agentId?: string;
    eventType?: string;
    decision?: string;
    from?: string;
    to?: string;
    anchored?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<AuditSearchResult> {
    const qs = new URLSearchParams();
    if (params.agentId) qs.set("agent_id", params.agentId);
    if (params.eventType) qs.set("event_type", params.eventType);
    if (params.decision) qs.set("decision", params.decision);
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    if (params.anchored !== undefined) qs.set("anchored", String(params.anchored));
    qs.set("limit", String(params.limit ?? 50));
    qs.set("offset", String(params.offset ?? 0));
    return request<AuditSearchResult>(`/audit/records?${qs.toString()}`);
  },
  auditProof(recordId: string): Promise<MerkleProofBundle> {
    return request<MerkleProofBundle>(`/audit/records/${recordId}/proof`);
  },
  auditExport(params: {
    agentId?: string;
    eventType?: string;
    decision?: string;
    from?: string;
    to?: string;
  }): Promise<string> {
    const qs = new URLSearchParams();
    if (params.agentId) qs.set("agent_id", params.agentId);
    if (params.eventType) qs.set("event_type", params.eventType);
    if (params.decision) qs.set("decision", params.decision);
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    return requestText(`/audit/export?${qs.toString()}`);
  },

  auditExportPdf(params: {
    agentId?: string;
    eventType?: string;
    decision?: string;
    from?: string;
    to?: string;
  }): Promise<Blob> {
    const qs = new URLSearchParams();
    if (params.agentId) qs.set("agent_id", params.agentId);
    if (params.eventType) qs.set("event_type", params.eventType);
    if (params.decision) qs.set("decision", params.decision);
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    return requestBlob(`/audit/export.pdf?${qs.toString()}`);
  },

  listTransactions(params: {
    agentId?: string;
    decision?: string;
    limit?: number;
    offset?: number;
  }): Promise<Transaction[]> {
    const qs = new URLSearchParams();
    if (params.agentId) qs.set("agent_id", params.agentId);
    if (params.decision) qs.set("decision", params.decision);
    qs.set("limit", String(params.limit ?? 50));
    qs.set("offset", String(params.offset ?? 0));
    return request<Transaction[]>(`/transactions?${qs.toString()}`);
  },
  metricsOverview(): Promise<MetricsOverview> {
    return request<MetricsOverview>("/metrics/overview");
  },
  killSwitch(scope: "agent" | "org", agentId?: string, reason?: string): Promise<unknown> {
    return request<unknown>("/kill-switch", {
      method: "POST",
      body: JSON.stringify({ scope, agent_id: agentId ?? null, reason: reason ?? "" }),
    });
  },
  resumeKillSwitch(scope: "agent" | "org", agentId?: string): Promise<unknown> {
    const qs = new URLSearchParams({ scope });
    if (agentId) qs.set("agent_id", agentId);
    return request<unknown>(`/kill-switch?${qs.toString()}`, { method: "DELETE" });
  },
};

export function downloadAuditExport(csv: string, filename = "audit_export.csv"): void {
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}