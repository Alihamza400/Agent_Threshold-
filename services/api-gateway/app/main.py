"""AgentThreshold API Gateway application entrypoint.

Phase 1 walking skeleton: health checks, auth/RBAC, org + agent registration,
scoped API keys. Rate limiting and screening pipeline arrive in Phase 2.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from at_shared.config import get_settings
from at_shared.db import engine
from at_shared.http_security import install_http_security
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.rate_limit import rate_limit_middleware
from app.routers import (
    agents,
    api_keys,
    approvals,
    audit,
    auth,
    metrics,
    orgs,
    policies,
    transactions,
)

settings = get_settings()

# CORS: explicit configured origins (comma-separated) win; otherwise permissive
# in development and locked down (none) in production. Wildcard origins never
# carry credentials (browser spec) — credentials are only allowed when the
# origin allow-list is explicit.
_configured_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_cors_origins = _configured_origins or (["*"] if not settings.is_production else [])
_cors_allow_credentials = bool(_configured_origins)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="AgentThreshold API",
    version="0.1.0",
    description="Real-Time Transaction Firewall for Autonomous AI Agents",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None if settings.is_production else "/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Org-Id",
        "X-Trace-Id",
    ],
)
app.middleware("http")(rate_limit_middleware(app))
# OWASP hardening: request-size cap (413) + security response headers.
install_http_security(
    app, max_body_bytes=settings.max_request_body_bytes, is_production=settings.is_production
)


# --------------------------------------------------------------------------
# Health checks
# --------------------------------------------------------------------------
@app.get("/healthz", tags=["ops"])
async def healthz() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.get("/readyz", tags=["ops"])
async def readyz() -> JSONResponse:
    """Liveness + dependency readiness (DB reachability). Fail-closed: 503."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "db": "unreachable"})
    return JSONResponse(content={"status": "ready", "db": "ok"})


# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(agents.router)
app.include_router(api_keys.router)
app.include_router(transactions.router)
app.include_router(policies.router)
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(metrics.router)
