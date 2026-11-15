import pytest

from wdchain.evidence.merkle import (
    EmptyStepError,
    MerkleError,
    chunk_digest,
    hash_pair,
    keccak256,
    leaf_from_chunk,
    leaf_from_digest,
    merkle_proof,
    merkle_root,
    verify_proof,
)


def _leaves(n):
    return [leaf_from_chunk(f"chunk-{i}".encode()) for i in range(n)]


def test_keccak_is_ethereum_keccak_not_sha3():
    # keccak256("") (SHA3-256("") would be a7ffc6f8...)
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"


def test_leaf_is_double_hash():
    data = b"some chunk"
    assert leaf_from_chunk(data) == keccak256(keccak256(data))
    assert leaf_from_digest(chunk_digest(data)) == keccak256(keccak256(data))


def test_hash_pair_is_sorted_and_commutative():
    a, b = _leaves(2)
    lo, hi = sorted([a, b])
    assert hash_pair(a, b) == hash_pair(b, a) == keccak256(lo + hi)


@pytest.mark.parametrize("n", [1, 2, 3, 7, 8])
def test_every_leaf_proof_verifies(n):
    leaves = _leaves(n)
    root = merkle_root(leaves)
    for i, leaf in enumerate(leaves):
        assert verify_proof(merkle_proof(leaves, i), root, leaf)


@pytest.mark.parametrize("n", [1, 2, 3, 7, 8])
def test_wrong_leaf_fails(n):
    leaves = _leaves(n)
    root = merkle_root(leaves)
    outsider = leaf_from_chunk(b"not in the tree")
    for i in range(n):
        proof = merkle_proof(leaves, i)
        assert not verify_proof(proof, root, outsider)
        # the single-hashed digest is not a valid leaf
        assert not verify_proof(proof, root, chunk_digest(f"chunk-{i}".encode()))


@pytest.mark.parametrize("n", [2, 3, 7, 8])
def test_tampered_sibling_fails(n):
    leaves = _leaves(n)
    root = merkle_root(leaves)
    for i, leaf in enumerate(leaves):
        proof = merkle_proof(leaves, i)
        assert proof, "every leaf has at least one sibling when n >= 2"
        for j in range(len(proof)):
            bad = list(proof)
            bad[j] = bytes([bad[j][0] ^ 0x01]) + bad[j][1:]
            assert not verify_proof(bad, root, leaf)


def test_tree_shape_odd_node_carried_up():
    l0, l1, l2 = _leaves(3)
    assert merkle_root([l0]) == l0
    assert merkle_root([l0, l1]) == hash_pair(l0, l1)
    assert merkle_root([l0, l1, l2]) == hash_pair(hash_pair(l0, l1), l2)
    assert merkle_proof([l0, l1, l2], 2) == [hash_pair(l0, l1)]
    assert merkle_proof([l0], 0) == []


def test_seven_leaves_shape():
    ls = _leaves(7)
    a, b, c = hash_pair(ls[0], ls[1]), hash_pair(ls[2], ls[3]), hash_pair(ls[4], ls[5])
    expected = hash_pair(hash_pair(a, b), hash_pair(c, ls[6]))
    assert merkle_root(ls) == expected
    assert merkle_proof(ls, 6) == [c, hash_pair(a, b)]


def test_empty_step_has_no_root():
    with pytest.raises(EmptyStepError):
        merkle_root([])


def test_bad_inputs():
    with pytest.raises(MerkleError):
        merkle_proof(_leaves(3), 3)
    with pytest.raises(MerkleError):
        merkle_root([b"short"])
