"""SDK test bootstrap.

Sets the test env explicitly so importing the SDK or the dev-only at-shared
never picks up the dev database. Mirrors the pattern used by every service
test suite (one shared test DB per pytest process).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_DB", "agentthreshold_test")

import pytest  # noqa: E402
from agentthreshold import AgentThresholdClient  # noqa: E402

WALLET = "0x" + "1" * 40
COUNTERPARTY = "0x" + "2" * 40


@pytest.fixture()
def client_factory():
    """A client factory that never opens a real network connection."""

    def _make(**kw):
        return AgentThresholdClient(
            base_url="http://screening.test",
            api_key="at_test_key_000000000000000000000000000000000000",
            **kw,
        )

    return _make
