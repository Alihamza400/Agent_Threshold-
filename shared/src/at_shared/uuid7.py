"""UUIDv7 generator — time-ordered, sortable, collision-resistant.

UUIDv7 is used for primary keys per the TRD (Section 7.1) so that rows are
naturally time-ordered, improving index locality for audit/baseline queries.

Layout (RFC 9562): 48-bit unix-ms timestamp | 4-bit version=7 | 12-bit rand_a
| 2-bit variant=10 | 62-bit rand_b.
Python 3.14 ships `uuid.uuid7`; this implementation provides parity on 3.12.
"""

from __future__ import annotations

import os
import time
import uuid

_VERSION_MASK = 0xF << 76  # version nibble at bits 48-51
_VARIANT_MASK = 0xC000000000000000  # variant bits 64-65


def uuid7() -> str:
    """Generate a UUIDv7 as a canonical string (Unix-epoch-ms + 74 bits of randomness)."""
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits (74 used)

    value = (ts_ms << 80) | rand
    value = (value & ~_VERSION_MASK) | (0x7 << 76)  # set version = 7
    value = (value & ~_VARIANT_MASK) | 0x8000000000000000  # set variant = 10

    return str(uuid.UUID(int=value))


def new_uuid() -> str:
    """Shortcut used by model defaults."""
    return uuid7()