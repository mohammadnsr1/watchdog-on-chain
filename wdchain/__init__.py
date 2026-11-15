"""wdchain: evidence commitment for WatchDog sessions.

This package turns a recorded WatchDog session directory into content-addressed chunks,
per-role / per-step manifests and keccak256 Merkle roots that a later smart contract can
check with OpenZeppelin's ``MerkleProof.verify``. It contains no blockchain code.
"""

__version__ = "0.1.0"
