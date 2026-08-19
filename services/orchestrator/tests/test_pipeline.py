"""Pipeline end-to-end tests (8.3): fail-closed semantics, stage budgets,
persistence, and the escalation queue."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from at_shared.models import Approval, AuditRecord, Transaction
from at_shared.schemas.simulation import SimulationResult, StateDiffEntry
from at_shared.schemas.tx import ChainId, DecisionType, ScreenRequest
from at_shared.uuid7 import uuid7
from blockchain.simulate import result_error
from blockchain.simulator import FakeSimulator
from orchestrator.pipeline import Pipeline
from screening_agents.llm import MockClient

WALLET = "0x" + "1" * 40
KNOWN_CP = "0x" + "2" * 40


def _request(agent_id, *, to_address=KNOWN_CP, value_wei=10**16, **overrides):
    base = dict(
        agent_id=agent_id,
        chain_id=ChainId.BASE,
        from_address=WALLET,
        to_address=to_address,
        value_wei=value_wei,
        task_context="transfer 0.01 eth to a known supplier",
    )
    base.update(overrides)
    return ScreenRequest(**base)


def _seed_known_tx(db, org_id, agent_id):
    db.add(
        Transaction(
            id=uuid7(),
            agent_id=agent_id,
            org_id=org_id,
            chain_id="base",
            from_address=WALLET,
            to_address=KNOWN_CP,
            value_wei=10**16,
            usd_value=0.01,
            raw_params={},
            decision="approve",
            confidence=90.0,
            reasons=[],
            status="screened",
            created_at=datetime.now(UTC),
        )
    )
    db.commit()


@pytest.fixture()
def make_pipeline(session_factory):
    def _make(*, simulator=None, llm=None, escalate_below_confidence=None, simulation_mode=None):
        return Pipeline(
            session_factory=session_factory,
            simulator=simulator or FakeSimulator(),
            llm=llm,
            escalate_below_confidence=escalate_below_confidence,
            simulation_mode=simulation_mode,
        )

    return _make


@pytest.mark.asyncio
async def test_screen_approves_within_policy(
    make_pipeline, org, make_agent, make_policy, db_session
):
    agent = make_agent(org.id, name="agent-approve")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    result = await make_pipeline().screen(_request(agent.id), org_id=org.id)

    assert result.decision.decision is DecisionType.APPROVE
    assert result.aggregate_confidence > 60
    assert result.decision.transaction_id

    tx = db_session.get(Transaction, result.decision.transaction_id)
    assert tx is not None
    assert tx.decision == "approve"
    assert tx.status == "approved"


@pytest.mark.asyncio
async def test_screen_simulation_mode_disabled_skips_simulation(
    make_pipeline, org, make_agent, make_policy, db_session
):
    agent = make_agent(org.id, name="agent-nosim")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    # "disabled" (dev/test only) approves without any simulator injected.
    result = await make_pipeline(simulation_mode="disabled").screen(
        _request(agent.id), org_id=org.id
    )

    assert result.decision.decision is DecisionType.APPROVE
    sim_timing = next(t for t in result.timings if t.name == "simulation")
    assert not sim_timing.ok
    assert "simulation_mode=disabled" in sim_timing.error


@pytest.mark.asyncio
async def test_screen_halted_agent_rejected_fail_closed(
    make_pipeline, org, make_agent, make_policy
):
    agent = make_agent(org.id, name="agent-halted", halted=True)
    make_policy(agent.id)

    result = await make_pipeline().screen(_request(agent.id), org_id=org.id)

    assert result.decision.decision is DecisionType.REJECT
    assert any("halt" in r.lower() for r in result.decision.reasons)


@pytest.mark.asyncio
async def test_screen_no_active_policy_rejects(make_pipeline, org, make_agent):
    agent = make_agent(org.id, name="agent-nopolicy")

    result = await make_pipeline().screen(_request(agent.id), org_id=org.id)

    assert result.decision.decision is DecisionType.REJECT
    assert any("policy" in r.lower() for r in result.decision.reasons)


@pytest.mark.asyncio
async def test_screen_org_scope_mismatch_rejects(make_pipeline, org, make_agent):
    other_org_id = "00000000-0000-0000-0000-0000000000ff"
    agent = make_agent(org.id, name="agent-scope")

    result = await make_pipeline().screen(_request(agent.id), org_id=other_org_id)

    assert result.decision.decision is DecisionType.REJECT
    assert any("scope" in r.lower() for r in result.decision.reasons)


@pytest.mark.asyncio
async def test_screen_simulation_error_escalates_fail_closed(
    make_pipeline, org, make_agent, make_policy, db_session
):
    agent = make_agent(org.id, name="agent-simerr")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    sim = FakeSimulator(
        result_factory=lambda req, gas_ceiling=None: result_error(req.chain_id, "RPC down")
    )
    result = await make_pipeline(simulator=sim).screen(_request(agent.id), org_id=org.id)

    # Fail-closed: simulation could not verify -> escalate, never approve.
    assert result.decision.decision is DecisionType.ESCALATE
    assert any("simulation" in r.lower() for r in result.decision.reasons)
    approval = (
        db_session.query(Approval)
        .filter_by(transaction_id=result.decision.transaction_id)
        .one_or_none()
    )
    assert approval is not None and approval.status == "pending"


@pytest.mark.asyncio
async def test_screen_simulation_reverted_rejects(
    make_pipeline, org, make_agent, make_policy, db_session
):
    agent = make_agent(org.id, name="agent-revert")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    def reverted(req, gas_ceiling=None):
        return SimulationResult(
            chain_id=req.chain_id,
            status="reverted",
            gas_used_wei=21000,
            gas_ceiling_used=False,
            revert_reason="evm revert: out of gas",
            simulated_at=datetime.now(UTC),
            simulator="anvil-fork",
        )

    result = await make_pipeline(simulator=FakeSimulator(result_factory=reverted)).screen(
        _request(agent.id), org_id=org.id
    )

    assert result.decision.decision is DecisionType.REJECT
    assert any("reverted" in r.lower() for r in result.decision.reasons)


@pytest.mark.asyncio
async def test_screen_confidence_below_threshold_escalates(
    make_pipeline, org, make_agent, make_policy, db_session
):
    agent = make_agent(org.id, name="agent-lowconf")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    # MockClient classifier conf is 0.85 -> aggregate ~83; force threshold 95.
    result = await make_pipeline(escalate_below_confidence=95.0).screen(
        _request(agent.id), org_id=org.id
    )

    assert result.decision.decision is DecisionType.ESCALATE
    assert result.aggregate_confidence < 95.0
    assert any("confidence" in r.lower() for r in result.decision.reasons)


class DrainLLM(MockClient):
    """Simulation Interpreter flags a balance drain (adversarial case)."""

    def _complete(self, system, user, schema):
        if schema.__name__ == "RiskSummary":
            return {
                "summary": "balance drain detected",
                "risk_level": "critical",
                "risk_tags": ["balance_drain"],
                "balance_drain": True,
            }
        return super()._complete(system, user, schema)


@pytest.mark.asyncio
async def test_screen_balance_drain_escalates(
    make_pipeline, org, make_agent, make_policy, db_session
):
    agent = make_agent(org.id, name="agent-drain")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    def draining(req, gas_ceiling=None):
        return SimulationResult(
            chain_id=req.chain_id,
            status="success",
            gas_used_wei=90000,
            gas_ceiling_used=False,
            state_diff=[
                StateDiffEntry(
                    address=req.to_address or WALLET,
                    slot="balance",
                    before="0x" + "0" * 64,
                    after="0x" + "0" * 63 + "1",
                )
            ],
            simulated_at=datetime.now(UTC),
            simulator="anvil-fork",
        )

    result = await make_pipeline(
        simulator=FakeSimulator(result_factory=draining), llm=DrainLLM()
    ).screen(_request(agent.id), org_id=org.id)

    assert result.aggregate_confidence == 0.0
    assert result.decision.decision is DecisionType.ESCALATE
    assert result.escalation_draft is not None


@pytest.mark.asyncio
async def test_screen_persists_audit_leaf(make_pipeline, org, make_agent, make_policy, db_session):
    agent = make_agent(org.id, name="agent-audit")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    result = await make_pipeline().screen(_request(agent.id), org_id=org.id)

    record = (
        db_session.query(AuditRecord).filter_by(transaction_id=result.decision.transaction_id).one()
    )
    assert record.event_type == "decision"
    assert len(record.event_hash) == 64


@pytest.mark.asyncio
async def test_stage_timings_recorded(make_pipeline, org, make_agent, make_policy, db_session):
    agent = make_agent(org.id, name="agent-timing")
    make_policy(agent.id)
    _seed_known_tx(db_session, org.id, agent.id)

    result = await make_pipeline().screen(_request(agent.id), org_id=org.id)

    names = {t.name for t in result.timings}
    assert {"kill_switch", "resolve", "classifier", "simulation", "context", "policy"} <= names
    assert all(t.ok for t in result.timings)
