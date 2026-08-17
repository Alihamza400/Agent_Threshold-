# AgentThreshold — Enterprise Implementation Plan

Real-Time Transaction Firewall for Autonomous AI Agents
Enterprise-Grade: Security · Optimization · Scalability
Derived from `AgentThreshold_Enterprise_TRD.docx` v1.0

---

## 1. Guiding Principles

Every phase and task in this plan is governed by five non-negotiable principles derived from the TRD:

| Principle | Rule | Enforced By |
|-----------|------|-------------|
| **Fail-Closed** | Any error, timeout, or low-confidence result → Block or Escalate. Never auto-approve. (SR-04) | Orchestration pipeline guardrails, circuit breakers |
| **Non-Custodial** | AgentThreshold never holds signing keys; simulation is always read-only (FR-CHAIN-01) | SDK boundary, tool allow-listing |
| **Zero Silent Bypass** | 100% of pipeline errors produce a logged fail-closed decision | Chaos testing, trace IDs |
| **Audit-Everything** | Every decision is append-only + on-chain Merkle anchored (FR-AUDIT-01) | Audit Service, AuditAnchor.sol |
| **Kill-Switch First** | Halt flag checked as step 0 of every screening request (FR-ADMIN-02) | Screening entry guard |

**Per-Service SLA Targets (NFR, Section 9):**
- p95 screening decision < 2s end-to-end; p95 simulation < 1.2s
- 10,000 tx/min sustained; 99.9% Screening API uptime
- RPO ≤ 5 min, RTO ≤ 30 min

---

## 2. Target Architecture & Repository Layout

### 2.1 Monorepo Structure

```
agentthreshold/
├── .github/workflows/          # CI/CD pipelines
├── infra/                      # Terraform, K8s manifests, Helm charts
│   ├── terraform/              # AWS/VPC/DB/Redis provision
│   ├── helm/                   # service charts
│   └── docker/                 # base images
├── contracts/                  # Solidity + Foundry
│   ├── src/AuditAnchor.sol
│   ├── src/PolicyRegistry.sol
│   └── test/
├── services/
│   ├── api-gateway/            # FastAPI: authN/authZ, rate-limit, routing
│   ├── orchestrator/           # Pipeline coordinator (fail-closed engine)
│   ├── screening-agents/       # Intent Classifier, Simulation Interpreter, Escalation Drafter
│   ├── anomaly-scorer/         # Rule-based v1 scorer + baseline service
│   ├── simulation/             # Anvil fork-per-request / Tenderly fallback
│   ├── policy-engine/          # Deterministic policy evaluation
│   ├── execution-adapter/      # Nonce management + broadcast
│   ├── audit-service/          # Append-only store + Merkle anchoring
│   ├── notification/           # Slack/webhook/email delivery
│   └── admin-api/              # Policy CRUD, approvals, agents, kill-switch
├── sdk/
│   ├── python/                 # agentthreshold-py
│   └── typescript/             # agentthreshold-ts
├── dashboard/                  # React + TypeScript + Tailwind
├── mcp-server/                 # simulate_transaction, get_policy, get_agent_history
├── prompt-registry/            # Versioned prompts (not inline in code)
├── shared/                     # schemas, libs, canonical tx model
└── docs/
```

### 2.2 Deployment Topology (Kubernetes)

```
                    ┌─────────────────────────────────────────┐
 Agent SDK ───────► │ API Gateway (HPA x8-16)                 │
                    │  - TLS, mTLS, rate limit, RBAC, WAF     │
                    └───────────────┬─────────────────────────┘
                                    ▼
                    ┌─────────────────────────────────────────┐
                    │ Orchestration Service (HPA)             │
                    │  Step0: kill-switch check               │
                    │  Step1: intent classifier (LLM)         │
                    │  Step2: simulation (Anvil fork)         │
                    │  Step3: anomaly score                   │
                    │  Step4: policy engine (deterministic)   │
                    │  → Approve / Reject / Escalate          │
                    └───────────┬──────────┬─────────┬────────┘
                                │          │         │
                     (Approve)  │   (Escalate)│  (Audit)  async
                                ▼          ▼         ▼
                   ┌─────────────────┐  ┌───────────────┐  ┌──────────────────┐
                   │ Execution       │  │ Approval      │  │ Audit Service    │
                   │ Adapter         │  │ Queue (Slack/ │  │ (append-only +   │
                   │ - nonce lock    │  │ webhook)      │  │  Merkle anchor   │
                   │ - broadcast     │  │               │  │  → AuditAnchor)  │
                   │ - confirmations │  └───────────────┘  └──────────────────┘
                   └─────────────────┘
```

Independent autoscaling: screening path scales on CPU/latency; admin path scales on request volume. Both isolated by dedicated node pools.

---

## 3. Phase 1 — Foundation (Infrastructure & AuthZ)

**Goal:** Repo + base infra + RBAC/SSO live. A user can log in, create an org, register an agent.

### 3.1 Tasks

| # | Task | Enterprise Notes (Security / Scalability) |
|---|------|-------------------------------------------|
| 1.1 | Repo scaffolding, monorepo tooling (Turborepo/uv), code conventions, lint/format | Pre-commit hooks, commit-signing policy, Dependabot |
| 1.2 | Postgres cluster (RDS/Aurora) — HA multi-AZ, PITR backups | Automated daily backups; monthly restore drill; RPO≤5m via logical replication |
| 1.3 | Redis cluster — TLS, AOF persistence, maxmemory policies | Used for nonce locks (SETNX), rate-limit counters, simulation cache, pub/sub |
| 1.4 | Secrets Manager (Vault/AWS KMS) + rotation | No plaintext secrets in code/config/logs; CI static scan |
| 1.5 | OIDC/OAuth2 SSO integration (Cognito/Okta) + RBAC middleware | Roles: Admin, Approver, Auditor, Developer (FR-AUTH-02); JWT scopes |
| 1.6 | API key service: scoped to agents, hash+store, shown once | Keys bound to agent IDs; unscoped → 403 (FR-AUTH-01) |
| 1.7 | Schema migrations (Alembic): org, user, agent, policy, transaction, audit tables | UUIDv7 PKs; FK ON DELETE RESTRICT for audit records |
| 1.8 | Docker base images + Dev Docker Compose + K8s cluster (EKS/GKE) | Dev: testnet. Staging: testnet + mainnet L2 read-only shadow |

### 3.2 Acceptance Criteria
- [ ] User authenticates via SSO and creates an org
- [ ] Admin registers an agent; agent bound to org + wallet address
- [ ] Auditor role receives 403 on policy-write endpoints (automated RBAC suite)
- [ ] `docker compose up` boots gateway, postgres, redis locally against testnet

---

## 4. Phase 2 — Backend Core (Policy Engine & Screening Skeleton)

**Goal:** A policy can be created and a mock transaction evaluated end-to-end.

### 4.1 Tasks

| # | Task | Notes |
|---|------|-------|
| 2.1 | Policy Engine core — spend limits, allow/deny lists, rate limits, time-of-day windows | Deterministic, pure, unit-testable; GIN index on allow_list |
| 2.2 | Policy CRUD API + versioning | Every change increments version; prior versions queryable (FR-ADMIN-01) |
| 2.3 | Transaction schema + canonical model (FR-DATA-01) | Round-trip mapping tests, 100% no-data-loss |
| 2.4 | `POST /v1/transactions/screen` skeleton (mock pipeline, no AI/chain yet) | Returns decision object; structured errors (400/403/429/503) |
| 2.5 | Kill-switch service + `POST /v1/kill-switch` | Checked first in pipeline; agent/org scope; propagates ≤1 request cycle |
| 2.6 | Rate limiting (per-org/per-agent) on gateway | Redis token bucket; 429 responses |
| 2.7 | Trace IDs + structured logging (OpenTelemetry → ELK) | 100% decisions traceable end-to-end |

### 4.2 Acceptance Criteria
- [ ] Policy created via API; over-limit mock tx rejected with rationale
- [ ] Kill-switch halts 100% of subsequent requests until cleared
- [ ] Within-policy tx returns Approve synchronously (< 2s p95 on mocked pipeline)

---

## 5. Phase 3 — AI Agents (Screening Intelligence)

**Goal:** Each agent passes ≥90% agreement on labeled sample sets. Structured outputs only.

### 5.1 Tasks

| # | Task | Security / Optimization Notes |
|---|------|-------------------------------|
| 3.1 | **Intent Classifier** — infers expected action class from task context + tool history | Input treated as **untrusted** (prompt-injection resistant); output schema-validated; advisory only |
| 3.2 | **Anomaly Scorer (rule-based v1)** — statistical deviation from rolling 90-day baseline | No LLM on hot path — deterministic, <500ms p95; flag large baseline shifts |
| 3.3 | **Simulation Interpreter** — LLM converts state-diff → plain-English risk summary | Structured output schema; adversarial test suite (balance-drain 100% detection) |
| 3.4 | **Escalation Drafting Agent** — drafts human approval request | Content only, zero execution authority |
| 3.5 | **Prompt Registry** — versioned, never inline | Every decision records prompt version for reproduction/audit |
| 3.6 | LLM client with bounded timeout (default 800ms) + retries + circuit breaker | Timeout → fail-closed; malformed output → fail-closed |
| 3.7 | Labeled test sets (200 samples) + agent unit suites | ≥90% agreement gate blocks CI otherwise |

### 5.2 Acceptance Criteria
- [ ] Classifier ≥90% agreement on 200-task labeled set
- [ ] Anomaly scorer deterministic for identical input; <500ms p95
- [ ] Interpreter identifies balance-drain in 100% adversarial cases
- [ ] Malformed/stale LLM output fails closed (never auto-approves)

---

## 6. Phase 4 — MCP / Tools

**Goal:** Read-only tools exposed via official MCP SDK; allow-listing enforced at server layer.

### 6.1 Tasks

| # | Task | Notes |
|---|------|-------|
| 4.1 | `simulate_transaction` MCP tool (chain_id, from, to, calldata, value → simulation result) | Consistent schema across chains (FR-MCP-01) |
| 4.2 | `get_policy`, `get_agent_history` read-only tools | Write attempts rejected at MCP server layer (FR-MCP-02) |
| 4.3 | Tool allow-listing + mTLS / signed requests | Mitigates MCP/tool spoofing (Section 8 threat model) |
| 4.4 | Response schema validation on every tool result | Malformed → treated as failure |
| 4.5 | Contract tests for tool schemas | Cross-chain consistency verified |

### 6.2 Acceptance Criteria
- [ ] Screening agents call tools only within allow-listed scope
- [ ] Write attempts return rejection; contract tests pass

---

## 7. Phase 5 — Blockchain Integration

**Goal:** Real testnet transaction simulated; state diff captured correctly; nonce managed safely.

### 7.1 Tasks

| # | Task | Security / Scalability Notes |
|---|------|------------------------------|
| 5.1 | RPC integration: Alchemy/Infura archive access (Ethereum + one L2, e.g. Base) | Chain-adapter interface → new chain = config not code |
| 5.2 | Fork-per-request simulation via Anvil; Tenderly managed fallback | Isolated fork per request — never mutates real state (FR-CHAIN-01) |
| 5.3 | `eth_call`, `eth_estimateGas`, `debug_traceCall` state-diff capture | Gas safety buffer 20% default; gas ceiling enforced |
| 5.4 | **Multi-provider RPC cross-check** | Primary + fallback compared; discrepancy → fail-closed escalate (threat: malicious RPC) |
| 5.5 | Nonce management: Redis-locked sequenced allocation per wallet | No two concurrent requests same nonce (FR-CHAIN-03) |
| 5.6 | Pending/confirmation monitoring (WebSocket) | Configurable confirmation depth (2 L2 / 12 mainnet); reorg detection |
| 5.7 | Price oracle (Chainlink) for cross-token USD normalization | Spend limits evaluated in common unit |

### 7.2 Acceptance Criteria
- [ ] Testnet tx simulated with correct state diff + gas estimate
- [ ] Gas-over-ceiling rejected pre-broadcast
- [ ] Concurrent screen requests for same wallet never share a nonce

---

## 8. Phase 6 — Smart Contracts

**Goal:** AuditAnchor + PolicyRegistry, 100% branch coverage, audited, deployed (testnet first, mainnet gated).

### 8.1 AuditAnchor.sol
- `mapping(uint256 => bytes32) batchRoots`, owner, authorized anchors
- `anchorBatch` / `getBatchRoot` / add-remove authorized anchor (onlyOwner)
- `BatchAnchored(batchId, merkleRoot, timestamp)`
- batchId **strictly increasing**; idempotent (revert on duplicate)
- UUPS proxy + 48h timelock; append-only history

### 8.2 PolicyRegistry.sol
- `mapping(bytes32 => bytes32[]) agentIdToPolicyHashHistory`
- `recordPolicyUpdate` / `getLatestPolicyHash` / `getPolicyHistory`
- Append-only (no delete/overwrite); single authorized writer
- UUPS proxy + timelock (same pattern)

### 8.3 Tasks

| # | Task | Notes |
|---|------|-------|
| 6.1 | Solidity contracts + Foundry scaffolding | No external calls / no value transfer (minimal attack surface) |
| 6.2 | Foundry test suite: fuzz + access-control + duplicate-batchId reverts | **100% branch coverage** required |
| 6.3 | Static analysis (Slither/Semgrep) | Run in CI |
| 6.4 | External audit (testnet first, findings resolved pre-mainnet) | Audit gate blocks mainnet deploy |
| 6.5 | Multi-sig ownership + deployment pipeline (2nd engineer sign-off) | Keys in Vault/KMS, rotated |
| 6.6 | Backend anchor batching: every 15 min or 1,000 records | Async — off the hot path |

### 8.4 Acceptance Criteria
- [ ] 100% branch coverage; duplicate batchId reverts (fuzz)
- [ ] Audit findings resolved before mainnet; anchor history append-only verified

---

## 9. Phase 7 — Frontend Dashboard

**Goal:** Admin configures policies; approver acts on escalations; auditor searches/exports logs.

### 9.1 Tasks

| # | Task | Notes |
|---|------|-------|
| 7.1 | Dashboard shell: SSO login, RBAC views per role | Auditor read-only enforced client + server |
| 7.2 | Policy configuration UI (per-agent) | Versioned; change notification to other admins |
| 7.3 | Approval queue UI | Plain-English risk summary; approve/reject/context actions |
| 7.4 | Audit log search + filter (agent, date range, decision) + export CSV/PDF | Pagination; export with Merkle proof bundle |
| 7.5 | Agent management + kill-switch UI | Confirm dialogs; reason captured |
| 7.6 | Real-time metrics widgets (pipeline latency, fail-closed rate) | Grafana embedded / dashboard API |

### 9.2 Acceptance Criteria
- [ ] Admin configures a policy via UI without code (BR-04)
- [ ] Approver acts on escalation from UI; state transitions correct (409 on double-decision)

---

## 10. Phase 8 — Integration (SDK, Pipeline Wiring, Escalation)

**Goal:** A sample agent wrapped with the SDK is screened end-to-end on testnet with correct decisions.

### 10.1 Tasks

| # | Task | Notes |
|---|------|-------|
| 8.1 | Python SDK (`agentthreshold-py`) — wraps signing call, intercepts before broadcast | `screen_and_sign()` / `screen()`; <1h wrap (UR-01) |
| 8.2 | TypeScript SDK (`agentthreshold-ts`) | Parity with Python SDK |
| 8.3 | Full pipeline wiring: classifier → simulation → anomaly → policy | Per-stage timeouts; aggregate confidence → escalate threshold |
| 8.4 | Escalation service: Slack/webhook delivery ≤5s, retry with backoff (99% within 5s) | Unresolved escalations expire → default reject |
| 8.5 | Execution Adapter: decision-token single-use validation, nonce lock, broadcast, confirm, reorg flag | Stuck-tx → RBF/cancel re-screened |
| 8.6 | Email daily digest (P2) | Org timezone; staging verified |
| 8.7 | E2E test: SDK-wrapped testnet agent → new unlisted address → escalated, no broadcast until approval | Mirrors Section 12 E2E scenario |

### 10.2 Acceptance Criteria
- [ ] SDK wrap-and-screen completes within 1 engineering hour (BR-03)
- [ ] Escalated tx never auto-executes; Slack notification sent; audit record anchored

---

## 11. Phase 9 — Security Hardening

**Goal:** All Section 8 threat mitigations implemented; pen test + chaos testing pass with P0/P1 resolved or risk-accepted.

### 11.1 Threat Mitigation Checklist (from TRD Section 8)

| Threat | Control Implemented | Verification |
|--------|--------------------|--------------|
| Prompt injection | Untrusted input, advisory-only LLM, schema validation | Adversarial test suite |
| MCP/tool spoofing | Allow-listing + mTLS + schema validation | Pen test |
| Malicious RPC | Multi-provider cross-check → fail-closed | Chaos injection |
| Contract vulns | No value transfer, append-only, multisig+timelock, audit | Foundry fuzz + audit |
| Key/session leakage | Non-custodial; optional ERC-4337 session keys (post-MVP) | Architecture review |
| Race/bypass | Redis nonce locks + single-use decision token | Concurrency tests |
| API abuse/DoS | Per-org/agent rate limits, autoscale, circuit breakers | Load test |
| Baseline poisoning | Rate-limited bounded baseline updates; large shifts flagged | Anomaly tests |
| Policy-change abuse | RBAC Admin-only, logged, on-chain anchored, notify admins | RBAC suite |
| Audit tampering | Append-only + Merkle anchor | Tamper-detection test |
| Emergency shutdown | Kill-switch step 0, fail-closed | Chaos test |

### 11.2 Tasks

| # | Task | Notes |
|---|------|-------|
| 9.1 | OWASP review of all APIs; WAF + TLS/mTLS hardening | CORS, headers, request size limits |
| 9.2 | Fail-closed chaos testing (inject timeouts/RPC failures/LLM failures) | Zero silent bypass verified |
| 9.3 | Third-party penetration test | P0/P1 findings resolved/risk-accepted |
| 9.4 | Static secrets scan + SAST/DAST in CI | No plaintext credentials |
| 9.5 | Dependency scanning (SCA), container image scanning | In CI + registry |
| 9.6 | Incident response runbook + on-call rotation | PagerDuty integration |

---

## 12. Phase 10 — Testing (Full Suite in CI)

| Test Type | Gate | CI Command |
|-----------|------|-----------|
| Unit (policy, scorer, contracts) | Coverage ≥ 80% backend, 100% contracts | `pytest`, `forge test` |
| Integration (full pipeline, mock chain) | Approve for within-policy testnet tx | `pytest -m integration` |
| Agent (labeled sets) | ≥90% agreement | `pytest -m agents` |
| Contract fuzz + access control | 100% branch | `forge coverage` |
| API (validation, RBAC, 403/409/429/503) | All error contracts | `pytest -m api` |
| Security (fail-closed, RPC tamper, audit tamper) | No silent bypass | `pytest -m security` |
| E2E (SDK-wrapped agent on testnet) | Escalation + no premature broadcast | `pytest -m e2e` |
| Load (10k tx/min) | p95 < 2s, zero fail-open | `k6`/`locust` |
| Chaos (timeouts, provider failures, kill-switch) | 100% fail-closed | `chaos-mesh` |

---

## 13. Phase 11 — Deployment & Go-Live

### 13.1 Environments

| Env | Infra | Chains | Gate |
|-----|-------|--------|------|
| Dev | Docker Compose + local K8s | Testnet | — |
| Staging | Full K8s cluster | Testnet + mainnet L2 read-only shadow | Auto on merge to main |
| Production | Production K8s, dedicated screening node pool | Mainnet + L2 | Manual, full suite green, 2nd-engineer sign-off for contracts |

### 13.2 Go-Live Sequence
1. Staging soak: 2 weeks, SLOs met (99.9% uptime, p95 < 2s)
2. Shadow-mode on mainnet L2 (read-only, no broadcast) — validate simulation accuracy
3. First design partner onboarded (limited agents, conservative thresholds)
4. Gradual traffic ramp: 10% → 50% → 100% with SLO watch
5. DR runbook drill + monthly restore drill verified

---

## 14. Timeline Estimate (11 Phases)

| Phase | Duration | Team |
|-------|----------|------|
| 1. Foundation | 2 wks | 2 BE + 1 DevOps |
| 2. Backend Core | 2 wks | 2 BE |
| 3. AI Agents | 3 wks | 1 ML/AI + 1 BE |
| 4. MCP/Tools | 1 wk | 1 BE |
| 5. Blockchain | 3 wks | 2 BE (blockchain) |
| 6. Smart Contracts | 3 wks (+2 wk audit) | 1 Solidity + 1 audit |
| 7. Frontend | 3 wks | 2 FE |
| 8. Integration | 3 wks | 2 BE + 1 FE |
| 9. Security | 2 wks | 1 Security |
| 10. Testing | 2 wks | All |
| 11. Deployment | 2 wks | All + DevOps |

**Total: ~26 weeks (6 months) with a 5-person cross-functional team**, overlapping where dependencies allow (Phase 7 runs parallel to Phases 5–6). Critical path: Phases 3 → 5 → 6 → 8 → 10 → 11.

---

## 15. Risk Register (Enterprise)

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Simulation latency on hot path | Missed time-sensitive use cases | Configurable fast-lane for pre-approved patterns (post-MVP); Tenderly fallback; per-stage budgets |
| False positives erode trust | Developer abandonment | Conservative defaults; low-friction override/escalation; false-positive monitoring dashboard |
| RPC provider manipulation | Malicious tx masked | Multi-provider cross-check → fail-closed |
| LLM output drift | Wrong risk summary | Prompt registry versioning; schema validation; canary prompts; daily drift eval |
| Baseline poisoning | Anomaly bypass | Bounded updates; large-shift flags; human review |
| On-chain gas spikes | Anchor cost | Batched anchoring (15m/1000 records); configurable anchor chain |
| Insider threat on policy | Weakened controls | RBAC Admin-only, dual-approval for limit changes, all changes anchored + notified |

---

## 16. Definition of Done (Project Level)

- [ ] All 9 MVP APIs live, contract-tested, documented (OpenAPI)
- [ ] All 4 AI agents ≥90% labeled-set agreement; advisory-only enforcement proven
- [ ] AuditAnchor + PolicyRegistry deployed on testnet + mainnet, audited, multisig-owned
- [ ] Zero silent bypass proven under chaos testing
- [ ] 10k tx/min sustained with p95 < 2s; 99.9% uptime for 2 consecutive weeks with live design partner
- [ ] RPO ≤ 5m / RTO ≤ 30m verified by restore drill
- [ ] Full RBAC, SSO, secrets rotation, monitoring/alerting live
- [ ] End-to-end SDK (Python + TS) wrapped and screened on testnet