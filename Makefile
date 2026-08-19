.PHONY: infra-up infra-down db-migrate db-upgrade db-downgrade api-gw orch notify test lint format seed sync

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

## Quality
test:
	uv run pytest -m "not security"

lint:
	uv run ruff check .

seed:
	uv run --directory shared python -m app.seed