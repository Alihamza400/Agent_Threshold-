"""Keccak256 Merkle tree (shared with at-shared).

The canonical implementation lives in `at_shared.merkle` so the api-gateway
and the audit-service produce byte-identical trees. This module re-exports it
for audit-service-internal imports.
"""

from __future__ import annotations

from at_shared.merkle import (
    LEAF_BYTES,
    MerkleError,
    leaf_hash,
    merkle_proof,
    merkle_root,
    verify_proof,
)

__all__ = [
    "LEAF_BYTES",
    "MerkleError",
    "leaf_hash",
    "merkle_proof",
    "merkle_root",
    "verify_proof",
]