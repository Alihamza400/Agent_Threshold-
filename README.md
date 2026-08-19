# AgentThreshold

Real-Time Transaction Firewall for Autonomous AI Agents.

A policy-enforcement and simulation proxy that intercepts every financial/on-chain action an AI agent attempts **before** it is signed or broadcast. It simulates the outcome, scores it against the agent's declared scope and historical behavior, enforces configurable policies, and either auto-approves, blocks, or escalates to a human approver — with a tamper-evident audit trail for every decision.

## Principles

- **Fail-Closed** — any error, timeout, or low-confidence result blocks or escalates; never auto-approves.
- **Non-Custodial** — never holds agent private keys; simulation is always read-only.
- **Zero Silent Bypass** — 100% of pipeline errors produce a logged fail-closed decision.
- **Audit-Everything** — every decision is append-only and on-chain Merkle anchored.
- **Kill-Switch First** — halt flag checked as step 0 of every screening request.

## Repository Layout

```
services/             Independently deployable backend services (FastAPI)
  api-gateway         AuthN/AuthZ, rate limiting, routing
  orchestrator        Screening pipeline coordinator (fail-closed engine)
  policy-engine       Deterministic policy evaluation
  screening-agents    Intent Classifier, Simulation Interpreter, Escalation Drafter
  anomaly-scorer      Rule-based v1 scorer + behavioral baseline
  simulation          Anvil fork-per-request / Tenderly fallback
  execution-adapter   Nonce management + broadcast + confirmation
  audit-service       Append-only store + Merkle anchoring
  notification        Slack/webhook/email delivery
  admin-api           Policy CRUD, approvals, agents, kill-switch
shared/               Canonical models, schemas, shared libs
contracts/            Solidity (AuditAnchor.sol, PolicyRegistry.sol) + Foundry
sdk/                  Python + TypeScript client SDKs
dashboard/            React + TypeScript + Tailwind admin UI
infra/                Terraform, Helm, Docker
prompt-registry/      Versioned AI prompts (never inline in code)
docs/                 Engineering docs
```

## Quick Start (Phase 1 walking skeleton)

```bash
# 1. Boot local infra
docker compose up -d postgres redis

# 2. Install workspace (all packages + dev tooling)
make sync
# or: uv sync --all-packages --group dev

# 3. Run migrations
uv run alembic upgrade head

# 4. Start the API gateway
uv run --directory services/api-gateway uvicorn app.main:app --reload
```

See `IMPLEMENTATION_PLAN.md` for the full 11-phase enterprise plan and `docs/` for design details.

## Status

Phase 1 (Foundation) — in progress.