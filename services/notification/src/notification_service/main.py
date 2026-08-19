"""FastAPI app hosting the escalation notification worker + health endpoints.

The worker always runs: expiry (fail-closed default reject) and delivery are
both local/DB concerns. If no webhooks are configured the worker still enforces
expiry; delivery is simply a no-op for every org.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from at_shared.config import get_settings
from at_shared.http_security import install_http_security
from fastapi import FastAPI

from notification_service.worker import NotificationRunner, build_runner

logger = logging.getLogger("notification_service.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner: NotificationRunner = build_runner()
    app.state.runner = runner
    settings = get_settings()
    task = asyncio.create_task(runner.run(poll_seconds=settings.notify_poll_seconds))
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(
    title="AgentThreshold Escalation Notification Service",
    description="Slack/webhook delivery with retry/backoff + fail-closed escalation expiry (8.4)",
    version="0.1.0",
    lifespan=lifespan,
)

_nsettings = get_settings()
install_http_security(
    app,
    max_body_bytes=_nsettings.max_request_body_bytes,
    is_production=_nsettings.is_production,
)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    runner: NotificationRunner = app.state.runner
    return {
        "status": "ok",
        "channel_count": len(runner.channels),
        "pending_deliveries": runner.outbox.pending_due_count(),
        "expiry_ttl_minutes": runner.expiry_ttl_minutes,
    }
