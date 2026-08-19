"""Orchestrator FastAPI service (plan 8.3).

Exposes the fail-closed screening pipeline as a standalone HTTP endpoint.
In a deployed topology the api-gateway routes ``POST /v1/transactions/screen``
here; the contract is the same ``ScreenRequest`` and a ``Decision`` extended
with aggregate confidence + per-stage timings for observability.

The service is independently authenticated with scoped API keys so it never
relies on the gateway being present to enforce authorization.
"""

from __future__ import annotations

from at_shared.config import get_settings
from at_shared.http_security import install_http_security
from at_shared.schemas.tx import Decision, DecisionType, ScreenRequest
from at_shared.uuid7 import uuid7
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from orchestrator.auth import get_api_key_context
from orchestrator.pipeline import Pipeline, PipelineResult

_pipeline = Pipeline()

app = FastAPI(
    title="AgentThreshold Orchestrator",
    description="Fail-closed screening pipeline (per-stage budgets, aggregate confidence)",
    version="0.1.0",
)

_osettings = get_settings()
install_http_security(
    app,
    max_body_bytes=_osettings.max_request_body_bytes,
    is_production=_osettings.is_production,
)


class StageTimingRead(BaseModel):
    name: str
    started_ms: int
    duration_ms: int
    timed_out: bool
    error: str | None = None


class ScreenResponse(BaseModel):
    decision: str
    reasons: list[str]
    confidence: float
    risk_summary: str | None = None
    policy_version: int | None = None
    transaction_id: str | None = None
    aggregate_confidence: float
    stage_timings: list[StageTimingRead] = []


def _reject(reason: str) -> PipelineResult:
    return PipelineResult(
        decision=Decision(
            decision=DecisionType.REJECT,
            reasons=[reason],
            confidence=0.0,
            risk_summary=f"Screening unavailable: {reason}",
        )
    )


def _to_response(result: PipelineResult) -> ScreenResponse:
    return ScreenResponse(
        decision=result.decision.decision.value,
        reasons=result.decision.reasons,
        confidence=result.decision.confidence,
        risk_summary=result.decision.risk_summary,
        policy_version=result.decision.policy_version,
        transaction_id=result.decision.transaction_id,
        aggregate_confidence=result.aggregate_confidence,
        stage_timings=[
            StageTimingRead(
                name=t.name,
                started_ms=t.started_ms,
                duration_ms=t.duration_ms,
                timed_out=t.timed_out,
                error=t.error,
            )
            for t in result.timings
        ],
    )


@app.post("/v1/screen", response_model=ScreenResponse)
async def screen(
    body: ScreenRequest,
    request: Request,
    api_ctx: dict = Depends(get_api_key_context),
) -> ScreenResponse:
    trace_id = request.headers.get("x-trace-id") or uuid7()

    if api_ctx["agent_ids"] and body.agent_id not in api_ctx["agent_ids"]:
        return _to_response(_reject("agent not in API key scope"))

    result = await _pipeline.screen(body, org_id=api_ctx["org_id"], trace_id=trace_id)
    return _to_response(result)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "orchestrator"}
