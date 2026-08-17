"""Escalation Drafting Agent (TRD 4.1).

Drafts the plain-English approval request shown to the human approver. Has no
execution authority — content only. Output is advisory to the approver.
"""

from __future__ import annotations

from screening_agents.llm import LLMClient
from screening_agents.prompts import get_prompt
from screening_agents.schemas import EscalationDraft


class EscalationDrafter:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    @property
    def prompt_version(self) -> str:
        _, version = get_prompt("escalation")
        return version

    def draft(self, *, agent_name: str, action_summary: str, anomaly_factors: list[str], policy_reasons: list[str]) -> EscalationDraft:
        system, _ = get_prompt("escalation")
        user = (
            f"Agent: {agent_name}\n"
            f"Transaction summary: {action_summary}\n"
            f"Anomaly factors: {', '.join(anomaly_factors) or 'none'}\n"
            f"Policy checks triggered: {', '.join(policy_reasons) or 'none'}\n\n"
            "Draft the approval request for a human approver."
        )
        return self._llm.complete(system, user, EscalationDraft)