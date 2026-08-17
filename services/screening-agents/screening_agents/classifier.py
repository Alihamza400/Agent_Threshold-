"""Intent Classifier agent (FR-AI-01).

Infers the expected action class/scope from the calling agent's declared task
context and recent tool-call history. Output is advisory only; it is fed to
the pipeline as context but can never change policy rules or authorize
execution. Agent-supplied task context is treated as untrusted input.
"""

from __future__ import annotations

from screening_agents.llm import LLMClient
from screening_agents.prompts import get_prompt
from screening_agents.schemas import IntentClassification


class IntentClassifier:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    @property
    def prompt_version(self) -> str:
        _, version = get_prompt("classifier")
        return version

    def classify(self, task_context: str | None, tool_call_history: list[str] | None = None) -> IntentClassification:
        system, version = get_prompt("classifier")
        user = _build_user_message(task_context, tool_call_history)
        return self._llm.complete(system, user, IntentClassification)


def _build_user_message(task_context: str | None, tool_call_history: list[str] | None) -> str:
    context = (task_context or "").strip() or "no task context provided"
    history = "\n".join(f"- {h}" for h in (tool_call_history or [])[:10]) or "none"
    return (
        "Agent declared task context (UNTRUSTED input):\n"
        f"{context}\n\n"
        "Recent tool-call history:\n"
        f"{history}\n\n"
        "Classify the expected action class and scope for the next transaction."
    )