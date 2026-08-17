"""AgentThreshold API Gateway application entrypoint.

Phase 1 walking skeleton: health checks, auth/RBAC, org + agent registration,
scoped API keys. Rate limiting and screening pipeline arrive in Phase 2.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from at_shared.config import get_settings
from at_shared.db import engine
from fastapi import FastAPI, Request
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
# in development and locked down (none) in production.
_configured_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_cors_origins = _configured_origins or (["*"] if not settings.is_production else [])


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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(rate_limit_middleware(app))


# --------------------------------------------------------------------------
# Middleware: structured request tracing header + security headers
# --------------------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains" if settings.is_production else ""
    return response


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