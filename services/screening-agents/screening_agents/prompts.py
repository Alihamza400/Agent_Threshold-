"""Prompt registry loader (TRD 4.6).

Prompts are versioned and stored outside code. Every screening decision must
record the exact prompt version used so it can be reproduced after updates.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from screening_agents.errors import ScreeningAgentError


def _default_registry_path() -> Path:
    """Repo-root prompt-registry/prompts.json; override with env var."""
    env = os.environ.get("PROMPT_REGISTRY_PATH")
    if env:
        return Path(env)
    # walk up from this module looking for the registry (works in-repo and
    # in an installed-package layout when the repo is on PYTHONPATH)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "prompt-registry" / "prompts.json"
        if candidate.exists():
            return candidate
    return here.parents[3] / "prompt-registry" / "prompts.json"


@lru_cache(maxsize=1)
def load_registry(path: Path | None = None) -> dict:
    p = path or _default_registry_path()
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise ScreeningAgentError(f"prompt registry not found at {p}") from exc
    except json.JSONDecodeError as exc:
        raise ScreeningAgentError(f"prompt registry {p} is not valid JSON") from exc


def get_prompt(name: str, version: str | None = None) -> tuple[str, str]:
    """Return (system_prompt, version) for a named agent.

    Raises ScreeningAgentError if the version is unknown — the pipeline treats
    this as a fail-closed condition (never screen with an unverifiable prompt).
    """
    registry = load_registry()
    entry = registry.get(name)
    if entry is None:
        raise ScreeningAgentError(f"unknown prompt agent: {name}")

    version = version or entry["current_version"]
    prompt = entry["prompts"].get(version)
    if prompt is None:
        raise ScreeningAgentError(f"unknown prompt version {version!r} for {name!r}")
    return prompt["system"], prompt["version"]