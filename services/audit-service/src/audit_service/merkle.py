"""Keccak256 Merkle tree used to anchor audit batches on-chain (FR-AUDIT-01).

The construction MUST match the Solidity expectation in
`contracts/test/MerkleCrossCheck.t.sol`: leaves are 32-byte keccak256 digests
and parents are `keccak256(left || right)`, with the odd trailing node
duplicated so every level is complete. Empty batches are rejected (fail-closed)
because the AuditAnchor contract rejects the zero root.
"""

from __future__ import annotations

from collections.abc import Sequence

from eth_hash.auto import keccak

from audit_service.errors import MerkleError

LEAF_BYTES = 32


def leaf_hash(data: bytes) -> bytes:
    """Canonical digest of an audit record (a Merkle leaf)."""
    return keccak(data)


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    """Root of the padded keccak256 tree. Raises on empty / malformed input."""
    level = _validate(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [keccak(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaves: Sequence[bytes], index: int) -> list[tuple[bytes, bool]]:
    """Sibling path for `leaves[index]` as `(sibling_hash, sibling_is_right)`."""
    level = _validate(leaves)
    if index < 0 or index >= len(leaves):
        raise MerkleError(f"leaf index {index} out of range for {len(leaves)} leaves")

    steps: list[tuple[bytes, bool]] = []
    idx = index
    while len(level) > 1:
        padded = level if len(level) % 2 == 0 else level + [level[-1]]
        sibling = padded[idx ^ 1]
        steps.append((sibling, idx % 2 == 0))
        level = [keccak(padded[i] + padded[i + 1]) for i in range(0, len(padded), 2)]
        idx //= 2
    return steps


def verify_proof(leaf: bytes, proof: Sequence[tuple[bytes, bool]], root: bytes, index: int) -> bool:
    """Recompute the root from `leaf` and `proof`; returns whether it matches."""
    digest = leaf
    for sibling, sibling_is_right in proof:
        digest = keccak(digest + sibling) if sibling_is_right else keccak(sibling + digest)
        index //= 2
    return digest == root


def _validate(leaves: Sequence[bytes]) -> list[bytes]:
    if not leaves:
        raise MerkleError("cannot build a tree over an empty batch")
    if any(len(leaf) != LEAF_BYTES for leaf in leaves):
        raise MerkleError("every leaf must be exactly 32 bytes")
    return list(leaves)