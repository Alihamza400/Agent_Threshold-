"""api_keys: service-to-service auth (FR-AUTH-01)

Raw key shown once at creation; only its sha256 hash is stored.
Scoped to agent IDs — calls for unbound agents return 403.
"""

from __future__ import annotations

import hashlib
import secrets
import string

_PREFIX_LEN = 12
_ALPHABET = string.ascii_letters + string.digits


def generate_api_key() -> tuple[str, str]:
    """Return (raw_key, prefix). Raw key is shown once and never persisted."""
    raw = "at_" + "".join(secrets.choice(_ALPHABET) for _ in range(40))
    return raw, raw[:_PREFIX_LEN]


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()