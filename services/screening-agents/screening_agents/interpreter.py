"""Simulation Interpreter agent (FR-AI-03).

Converts a raw simulated state diff into a structured, plain-English risk
summary. Adversarial test suite requires 100% detection of balance-drain
scenarios. Advisory only.
"""

from __future__ import annotations

import json

from screening_agents.llm import LLMClient
from screening_agents.prompts import get_prompt
from screening_agents.schemas import RiskSummary


class SimulationInterpreter:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    @property
    def prompt_version(self) -> str:
        _, version = get_prompt("interpreter")
        return version

    def interpret(self, state_diff: dict) -> RiskSummary:
        system, _ = get_prompt("interpreter")
        user = (
            "Raw simulated state diff (JSON):\n"
            f"{json.dumps(state_diff, default=str)}\n\n"
            "Produce a plain-English risk summary with structured risk tags."
        )
        return self._llm.complete(system, user, RiskSummary)