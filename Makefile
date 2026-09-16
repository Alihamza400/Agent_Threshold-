.PHONY: infra-up infra-down db-migrate db-upgrade db-downgrade api-gw orch notify test test-cov contract lint format sync secrets sast dast audit security images scan

## Infrastructure
infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down

## Workspace
sync:
	uv sync --all-packages --group dev

## Database
db-migrate:
	cd shared && uv run alembic revision --autogenerate -m "$(m)"

db-upgrade:
	cd shared && uv run alembic upgrade head

db-downgrade:
	cd shared && uv run alembic downgrade -1

## Services
api-gw:
	uv run --directory services/api-gateway uvicorn app.main:app --reload --port 8000

orch:
	uv run --directory services/orchestrator uvicorn orchestrator.main:app --reload --port 8001

notify:
	uv run --directory services/notification uvicorn notification_service.main:app --reload --port 8002

seed:
	uv run --directory shared python -m app.seed

## Quality
test:
	uv run pytest -m "not security and not dast"

test-cov:
	uv run pytest -m "not security and not dast" --cov=services --cov=shared --cov-report=term-missing --cov-fail-under=80

contract:
	uv run pytest sdk/python/tests -m contract -v

lint:
	uv run ruff check .

# Static secrets scan (gitleaks) + hardcoded-secret blocklist
secrets:
	command -v gitleaks >/dev/null 2>&1 || (echo "gitleaks not installed (brew install gitleaks / see CI job)"; exit 2)
	gitleaks git --redact --no-banner
	./scripts/check-secrets.sh

# Static application security testing (bandit)
sast:
	uvx bandit -q -c pyproject.toml -r services shared sdk

# Dynamic security probes against the running gateway (needs infra up)
dast:
	uv run pytest tests/dast -m dast

# Dependency / supply-chain audit (needs .venv synced)
audit:
	uv run pip-audit

security: secrets sast audit

# Container images for every service (multi-stage, non-root, slim runtime)
images:
	docker buildx bake

# Container + IaC vulnerability scan (needs `images` built locally)
scan:
	trivy image --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml --exit-code 1 agentthreshold/api-gateway:latest
	trivy image --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml --exit-code 1 agentthreshold/notification:latest
	trivy image --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml --exit-code 1 agentthreshold/execution:latest
	trivy image --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml --exit-code 1 agentthreshold/audit-service:latest
	trivy image --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml --exit-code 1 agentthreshold/mcp-server:latest
	trivy image --severity HIGH,CRITICAL --ignorefile .trivyignore.yaml --exit-code 1 agentthreshold/orchestrator:latest
	trivy config --severity HIGH,CRITICAL --exit-code 1 .

format:
	uv run ruff format .