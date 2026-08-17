// Canonical API types mirroring shared/src/at_shared/schemas.

export type Role = "admin" | "approver" | "auditor" | "developer";

export interface CurrentUser {
  id: string;
  org_id: string;
  email: string;
  role: Role;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Agent {
  id: string;
  org_id: string;
  name: string;
  wallet_address: string;
  status: "active" | "paused" | "halted";
  halted: boolean;
  halt_reason: string | null;
  created_at: string;
}

export interface AgentRegistered {
  agent: Agent;
  default_policy_id: string | null;
}

export interface Policy {
  agent_id: string;
  version: number;
  spend_limit_usd: number | null;
  daily_spend_limit_usd: number | null;
  allow_list: string[];
  deny_list: string[];
  rate_limit_per_minute: number | null;
  active_from_minute: number | null;
  active_to_minute: number | null;
  gas_ceiling: number | null;
  anomaly_threshold: number;
  is_active: boolean;
  created_by: string;
  created_at: string;
}

export interface PolicyUpdate {
  spend_limit_usd?: number | null;
  daily_spend_limit_usd?: number | null;
  allow_list?: string[];
  deny_list?: string[];
  rate_limit_per_minute?: number | null;
  active_from_minute?: number | null;
  active_to_minute?: number | null;
  gas_ceiling?: number | null;
  anomaly_threshold?: number;
  change_note?: string | null;
}

export interface Approval {
  id: string;
  org_id: string;
  agent_id: string;
  agent_name: string;
  transaction_id: string;
  chain_id: string;
  from_address: string;
  to_address: string | null;
  value_wei: number;
  decision: string;
  status: string;
  reasons: string[];
  risk_summary: string | null;
  confidence: number;
  expires_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface Transaction {
  id: string;
  agent_id: string;
  org_id: string;
  chain_id: string;
  from_address: string;
  to_address: string | null;
  value_wei: number;
  usd_value: number | null;
  token: string | null;
  decision: string;
  confidence: number;
  risk_summary: string | null;
  reasons: string[];
  policy_version: number | null;
  status: string;
  screened_ms: number | null;
  created_at: string;
}

export interface AuditRecord {
  id: string;
  org_id: string;
  agent_id: string;
  event_type: string;
  event_hash: string;
  details: Record<string, unknown>;
  anchored_batch_id: number | null;
  created_at: string;
}

export interface AuditSearchResult {
  items: AuditRecord[];
  total: number;
}

export interface MerkleProofBundle {
  record_id: string;
  leaf: string;
  root: string;
  batch_id: number;
  anchored_at: string;
  proof: { hash: string; is_right: boolean }[];
  verified: boolean;
}

export interface MetricsOverview {
  window_hours: number;
  total_transactions_24h: number;
  decision_mix: { approve: number; reject: number; escalate: number };
  fail_closed_rate: number;
  latency_ms: { p50: number | null; p95: number | null };
  daily_series: { days: string[]; counts: number[] };
  approvals: { pending: number; resolved_24h: number; avg_decision_hours: number | null };
}