"""Merkle tree tests incl. the cross-language fixture locked with Solidity."""

import pytest
from audit_service.errors import MerkleError
from audit_service.merkle import leaf_hash, merkle_proof, merkle_root, verify_proof


def test_single_leaf_root_is_leaf():
    leaf = leaf_hash(b"record")
    assert merkle_root([leaf]) == leaf


def test_empty_batch_raises():
    with pytest.raises(MerkleError):
        merkle_root([])


def test_malformed_leaf_raises():
    with pytest.raises(MerkleError):
        merkle_root([b"short"])


def test_matches_solidity_fixture():
    leaves = [leaf_hash(f"leaf{i}".encode()) for i in range(5)]
    # Locked with contracts/test/MerkleCrossCheck.t.sol — a change on either
    # side (pairing, padding, hashing) breaks this build.
    assert merkle_root(leaves).hex() == "b0cb5b3f0776b1932410c3ffbb811f62a8f26a361d22b818e4e92965a6014da5"


def test_proof_verifies_for_every_leaf_odd_and_even_trees():
    for n in (1, 2, 3, 4, 5, 7, 8, 9):
        leaves = [leaf_hash(f"r{i}".encode()) for i in range(n)]
        root = merkle_root(leaves)
        for index in range(n):
            proof = merkle_proof(leaves, index)
            assert verify_proof(leaves[index], proof, root, index)
            # single-leaf trees have an empty proof and cannot distinguish peers
            if proof:
                assert not verify_proof(leaves[(index + 1) % n], proof, root, index)


def test_proof_out_of_range_raises():
    leaves = [leaf_hash(b"a"), leaf_hash(b"b")]
    with pytest.raises(MerkleError):
        merkle_proof(leaves, 2)


def test_root_deterministic():
    leaves = [leaf_hash(f"x{i}".encode()) for i in range(6)]
    assert merkle_root(leaves) == merkle_root(leaves)


def test_padded_odd_last_is_used_in_parent():
    # 3 leaves: parent of the padded level hashes (leaf1, leaf2) and the
    # duplicated leaf2 pairs with itself only if padding is applied.
    l0, l1, l2 = (leaf_hash(b"a"), leaf_hash(b"b"), leaf_hash(b"c"))
    root = merkle_root([l0, l1, l2])
    from eth_hash.auto import keccak

    assert root == keccak(keccak(l0 + l1) + keccak(l2 + l2))