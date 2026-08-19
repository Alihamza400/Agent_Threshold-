"""Phase 8 fail-closed screening orchestrator (FR-ORCH-01/02, plan 8.3).

Owns the pipeline the api-gateway previously ran inline:

  step 0  kill-switch check             (deterministic, DB, checked FIRST)
  step 1  agent + active policy         (deterministic, DB)
  step 2  intent classifier             (advisory LLM, bounded, never approves)
  step 3  fork-per-request simulation   (chain, bounded, fail-closed)
  step 4  anomaly + engine context      (deterministic, DB)
  step 5  policy evaluation             (deterministic, pure)
  step 6  risk interpretation           (advisory LLM; escalate/non-trivial only)
  step 7  aggregate confidence + escalate threshold
  step 8  persist decision + audit leaf + escalation queue

Fail-closed (SR-04): every stage runs under a wall-clock budget. A gating
stage that errors or times out rejects; a simulation that cannot verify
escalates; a reverted simulation rejects. The classifier/interpreter/drafter
are advisory and can never approve — their failure is recorded, never a
silent auto-approve.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from anomaly_scorer.scorer import AnomalyResult
from at_shared.audit_events import audit_leaf, write_audit_record
from at_shared.config import get_settings
from at_shared.db import SessionLocal
from at_shared.models import Agent, Approval, Policy, Transaction
from at_shared.schemas.simulation import SimulateRequest, SimulationResult
from at_shared.schemas.tx import Decision, DecisionType, ScreenRequest
from at_shared.uuid7 import uuid7
from blockchain.simulate import simulate_transaction as run_simulation
from policy_engine.engine import PolicyData, evaluate
from screening_agents.classifier import IntentClassifier
from screening_agents.escalation import EscalationDrafter
from screening_agents.interpreter import SimulationInterpreter
from screening_agents.llm import get_llm_client
from screening_agents.schemas import EscalationDraft, RiskSummary
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.baseline import refresh_baseline
from orchestrator.confidence import aggregate_confidence
from orchestrator.context import build_screening_context
from orchestrator.errors import StageBudgetError, StageError
from orchestrator.stages import StageBudget, StageTiming, run_stage


@dataclass
class PipelineResult:
    """Outcome of a screening run, including per-stage observability."""

    decision: Decision
    timings: list[StageTiming] = field(default_factory=list)
    aggregate_confidence: float = 0.0
    simulation: SimulationResult | None = None
    anomaly: AnomalyResult | None = None
    escalation_draft: EscalationDraft | None = None


class Pipeline:
    """The fail-closed screening pipeline. One instance per worker."""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        simulator: Any | None = None,
        budgets: StageBudget | None = None,
        escalate_below_confidence: float | None = None,
        session_factory: Callable[[], Session] | None = None,
        simulation_mode: str | None = None,
    ) -> None:
        self._llm = llm or get_llm_client()
        self._classifier = IntentClassifier(self._llm)
        self._interpreter = SimulationInterpreter(self._llm)
        self._drafter = EscalationDrafter(self._llm)
        self._simulator = simulator
        self._budgets = budgets or StageBudget()
        settings = get_settings()
        self._escalate_below_confidence = (
            escalate_below_confidence
            if escalate_below_confidence is not None
            else settings.escalate_below_confidence
        )
        if simulation_mode is None:
            simulation_mode = settings.simulation_mode
        # Fail-closed default: anything other than an explicit "disabled" keeps
        # simulation required. "disabled" is DEV/TEST only (operator choice,
        # never silent).
        self._simulation_mode = (
            simulation_mode if simulation_mode in {"required", "disabled"} else "required"
        )
        self._session_factory = session_factory or SessionLocal

    # ------------------------------------------------------------------ API
    async def screen(
        self,
        request: ScreenRequest,
        *,
        org_id: str,
        trace_id: str | None = None,
    ) -> PipelineResult:
        """Run the full pipeline for one transaction.

        Gating failures return a fail-closed (reject/escalate) PipelineResult;
        only an unexpected persistence failure raises, which the API layer maps
        to a fail-closed 503 rather than ever auto-approving.
        """
        started = time.monotonic()
        timings: list[StageTiming] = []
        trace_id = trace_id or uuid7()

        with self._session_factory() as db:
            # ---- step 0: kill-switch (FR-ADMIN-02) — checked FIRST ---------
            agent, ok = await self._stage(
                timings,
                started,
                "kill_switch",
                asyncio.to_thread(self._load_agent, db, request.agent_id),
            )
            if not ok:
                return self._fail_closed("kill-switch check unavailable", timings)
            if agent is None or agent.org_id != org_id:
                return self._fail_closed("agent not found for this key scope", timings)
            if agent.halted:
                return self._fail_closed(
                    f"agent halted: {agent.halt_reason or 'kill-switch active'}", timings
                )

            # ---- step 1: active policy (deterministic) ---------------------
            policy, ok = await self._stage(
                timings,
                started,
                "resolve",
                asyncio.to_thread(self._active_policy, db, request.agent_id),
            )
            if not ok:
                return self._fail_closed("policy resolution unavailable", timings)
            if policy is None:
                return self._fail_closed("no active policy for agent", timings)

            # ---- step 2: advisory intent classifier (bounded) --------------
            classification, _ = await self._stage(
                timings,
                started,
                "classifier",
                asyncio.to_thread(self._classifier.classify, request.task_context),
            )
            classifier_conf = classification.confidence if classification else None
            intent_note = (
                f"intent={classification.action_class.value} conf={classification.confidence:.2f}"
                if classification
                else None
            )

            # ---- step 3: fork simulation (bounded, fail-closed) ------------
            simulation: SimulationResult | None = None
            simulation_error: str | None = None
            if self._simulation_mode == "disabled":
                # DEV/TEST only: simulation skipped by explicit operator choice.
                # Never used in production (fail-closed default is "required").
                timings.append(
                    StageTiming(
                        name="simulation",
                        started_ms=int((time.monotonic() - started) * 1000),
                        duration_ms=0,
                        error="simulation_mode=disabled (dev only)",
                    )
                )
            else:
                simulation, sim_ok = await self._stage(
                    timings,
                    started,
                    "simulation",
                    run_simulation(
                        SimulateRequest(
                            agent_id=request.agent_id,
                            chain_id=request.chain_id,
                            from_address=request.from_address,
                            to_address=request.to_address,
                            value_wei=request.value_wei,
                            calldata=request.calldata,
                        ),
                        gas_ceiling=policy.gas_ceiling,
                        simulator=self._simulator,
                    ),
                )
                if not sim_ok:
                    simulation_error = "simulation unavailable (stage failed)"
                elif simulation.status == "error":
                    simulation_error = (
                        f"simulation unavailable: {simulation.revert_reason or 'backend error'}"
                    )

            # ---- step 4: anomaly + engine context (deterministic) ----------
            context, ok = await self._stage(
                timings,
                started,
                "context",
                asyncio.to_thread(
                    build_screening_context,
                    db,
                    request.agent_id,
                    request.to_address,
                    request.value_wei,
                    float(request.value_wei) / 1e18,
                ),
            )
            if not ok:
                return self._fail_closed("screening context unavailable", timings)

            # ---- step 5: deterministic policy evaluation ------------------
            result, ok = await self._stage(
                timings,
                started,
                "policy",
                asyncio.to_thread(
                    evaluate,
                    PolicyData.from_orm(policy),
                    request.to_address,
                    request.value_wei,
                    request.gas_limit,
                    context.engine_ctx,
                ),
            )
            if not ok:
                return self._fail_closed("policy evaluation unavailable", timings)

            # ---- step 6: advisory risk interpretation ----------------------
            non_trivial = (
                simulation is not None
                and simulation.status == "success"
                and bool(simulation.state_diff)
            )
            risk: RiskSummary | None = None
            if result.decision is DecisionType.ESCALATE or non_trivial:
                risk, _ = await self._stage(
                    timings,
                    started,
                    "interpreter",
                    asyncio.to_thread(
                        self._interpreter.interpret,
                        [e.model_dump() for e in (simulation.state_diff if simulation else [])],
                    ),
                )

            # ---- step 7: aggregate confidence + escalate threshold ---------
            confidence = aggregate_confidence(
                classifier_conf=classifier_conf,
                anomaly_score=context.anomaly_score,
                risk_level=risk.risk_level if risk else None,
                balance_drain=bool(risk and risk.balance_drain),
            )
            reasons = list(result.reasons)
            if intent_note:
                reasons.append(intent_note)
            final = result.decision

            if simulation is not None and simulation.status == "reverted":
                final = DecisionType.REJECT
                reasons.append(
                    f"simulation reverted: {simulation.revert_reason or 'transaction would fail on-chain'}"
                )
            elif final is not DecisionType.REJECT and simulation_error:
                final = DecisionType.ESCALATE
                reasons.append(simulation_error)

            if final is DecisionType.APPROVE and confidence < self._escalate_below_confidence:
                final = DecisionType.ESCALATE
                reasons.append(
                    f"aggregate confidence {confidence:.1f} below escalate threshold "
                    f"{self._escalate_below_confidence:.1f}"
                )

            # ---- step 8: escalation draft (advisory, escalate only) --------
            draft: EscalationDraft | None = None
            if final is DecisionType.ESCALATE:
                draft, _ = await self._stage(
                    timings,
                    started,
                    "escalation_draft",
                    asyncio.to_thread(
                        self._drafter.draft,
                        agent_name=agent.name,
                        action_summary=(
                            request.task_context
                            or f"{request.value_wei} wei to {request.to_address or 'contract deployment'}"
                        ),
                        anomaly_factors=[
                            f["detail"]
                            for f in (
                                context.anomaly.contributing_factors if context.anomaly else []
                            )
                        ],
                        policy_reasons=reasons,
                    ),
                )

            # ---- persist decision + audit leaf + escalation queue ----------
            risk_summary = (
                draft.summary if draft else ("; ".join(reasons) if reasons else "within policy")
            )
            tx = Transaction(
                id=uuid7(),
                agent_id=request.agent_id,
                org_id=org_id,
                chain_id=request.chain_id.value,
                from_address=request.from_address,
                to_address=request.to_address,
                value_wei=request.value_wei,
                usd_value=context.engine_ctx.usd_value,
                token=request.token,
                calldata=request.calldata,
                gas_limit=request.gas_limit,
                gas_price_wei=request.gas_price_wei,
                raw_params=request.model_dump(),
                decision=final.value,
                confidence=confidence,
                risk_summary=risk_summary,
                reasons=reasons,
                policy_version=result.policy_version,
                status={
                    DecisionType.APPROVE: "approved",
                    DecisionType.REJECT: "rejected",
                    DecisionType.ESCALATE: "escalated",
                }[final],
                trace_id=trace_id,
                screened_ms=int((time.monotonic() - started) * 1000),
            )
            db.add(tx)
            db.flush()

            leaf = audit_leaf(
                "decision",
                org_id,
                request.agent_id,
                tx.id,
                final.value,
                request.value_wei,
                request.to_address or "",
                result.policy_version,
            )
            write_audit_record(
                db,
                org_id=org_id,
                agent_id=request.agent_id,
                transaction_id=tx.id,
                event_type="decision",
                details={
                    "transaction_id": tx.id,
                    "decision": final.value,
                    "to_address": request.to_address,
                    "from_address": request.from_address,
                    "value_wei": request.value_wei,
                    "chain_id": request.chain_id.value,
                    "policy_version": result.policy_version,
                    "agent_name": agent.name,
                    "aggregate_confidence": confidence,
                    "simulator": simulation.simulator if simulation else None,
                    "simulation_status": simulation.status if simulation else None,
                },
                leaf=leaf,
            )

            if final is DecisionType.ESCALATE:
                db.add(
                    Approval(
                        id=uuid7(),
                        org_id=org_id,
                        agent_id=request.agent_id,
                        transaction_id=tx.id,
                        decision="escalate",
                        status="pending",
                        reasons=reasons,
                        risk_summary=risk_summary,
                        confidence=confidence,
                        expires_at=datetime.now(UTC)
                        + timedelta(minutes=get_settings().escalation_ttl_minutes),
                    )
                )

            db.commit()
            db.refresh(tx)

            # keep the behavioral baseline current (FR-DATA-02); throttled and
            # best-effort — a failure here must not fail an already-decided tx.
            with contextlib.suppress(Exception):  # noqa: BLE001 - maintenance path
                refresh_baseline(db, request.agent_id)

        return PipelineResult(
            decision=Decision(
                decision=final,
                reasons=reasons,
                confidence=confidence,
                risk_summary=risk_summary,
                policy_version=result.policy_version,
                transaction_id=tx.id,
            ),
            timings=timings,
            aggregate_confidence=confidence,
            simulation=simulation,
            anomaly=context.anomaly,
            escalation_draft=draft,
        )

    # ------------------------------------------------------------- internals
    async def _stage(
        self,
        timings: list[StageTiming],
        started: float,
        name: str,
        coro: Awaitable[Any],
    ) -> tuple[Any, bool]:
        """Run a stage under its budget; returns ``(value, ok)``.

        ``ok is False`` on timeout or failure (a StageTiming is recorded).
        Advisory stages ignore the boolean; gating stages fail closed on it.
        """
        budget = self._budgets.for_stage(name)
        started_ms = int((time.monotonic() - started) * 1000)
        try:
            value, timing = await run_stage(name, budget, coro, started_ms=started_ms)
        except (StageBudgetError, StageError) as exc:
            timings.append(
                StageTiming(
                    name=name,
                    started_ms=started_ms,
                    timed_out=isinstance(exc, StageBudgetError),
                    error=str(exc),
                )
            )
            return None, False
        timings.append(timing)
        return value, True

    @staticmethod
    def _load_agent(db: Session, agent_id: str) -> Agent | None:
        return db.scalar(select(Agent).where(Agent.id == agent_id))

    @staticmethod
    def _active_policy(db: Session, agent_id: str) -> Policy | None:
        return db.scalar(
            select(Policy)
            .where(Policy.agent_id == agent_id, Policy.is_active.is_(True))
            .order_by(Policy.version.desc())
            .limit(1)
        )

    def _fail_closed(self, reason: str, timings: list[StageTiming]) -> PipelineResult:
        """Fail-closed decision: block/escalate, never auto-approve (SR-04)."""
        return PipelineResult(
            decision=Decision(
                decision=DecisionType.REJECT,
                reasons=[reason],
                confidence=0.0,
                risk_summary=f"Screening unavailable: {reason}",
            ),
            timings=timings,
            aggregate_confidence=0.0,
        )
