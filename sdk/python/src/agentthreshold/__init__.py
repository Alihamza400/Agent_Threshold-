"""AgentThreshold — real-time transaction firewall for autonomous AI agents.

The SDK intercepts every on-chain action BEFORE it is signed or broadcast:
it screens against the AgentThreshold gateway and only signs when the
pipeline approves. It is non-custodial — your signer (and key) never leaves
your process.
"""

from __future__ import annotations

from .client import AgentThresholdClient
from .errors import (
    AgentThresholdError,
    ScreeningError,
    ScreeningEscalatedError,
    ScreeningRejectedError,
    ScreeningUnavailableError,
    TransportError,
    UnauthorizedError,
)
from .schemas import ChainId, Decision, DecisionType, ScreenRequest
from .signing import Signer, unsigned_tx_to_screen_request

__version__ = "0.1.0"

__all__ = [
    "AgentThresholdClient",
    "AgentThresholdError",
    "ChainId",
    "Decision",
    "DecisionType",
    "ScreenRequest",
    "ScreeningError",
    "ScreeningEscalatedError",
    "ScreeningRejectedError",
    "ScreeningUnavailableError",
    "Signer",
    "TransportError",
    "UnauthorizedError",
    "unsigned_tx_to_screen_request",
]
