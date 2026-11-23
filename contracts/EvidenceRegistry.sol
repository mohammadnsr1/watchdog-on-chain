// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// An "import" pulls in code from another file. OpenZeppelin is a widely used library of
// audited Solidity contracts; MerkleProof implements the standard proof check.
// The "@openzeppelin/" prefix is a remapping configured in foundry.toml.
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

/// @title EvidenceRegistry
/// @notice Anchors one Merkle root per (session, role, step) of a WatchDog run.
///
/// Blockchain primer for this file:
///  - A *contract* is code plus storage living at an address on the chain. Its storage is
///    public, permanent and replicated on every node.
///  - Writing to storage costs *gas*, paid by whoever sends the transaction. Reading from
///    outside costs nothing, which is why the read-only functions below are marked `view`.
///  - `msg.sender` is the address that signed the transaction. It is how the chain attributes
///    a commit to an agent: we never take the committer as an argument, because an argument
///    could be forged and `msg.sender` cannot.
///  - `revert` aborts the transaction and undoes every state change in it. We use it to make
///    commits write-once.
///  - `event` + `emit` write a cheap, indexed log entry. Logs are not readable by contracts
///    but off-chain clients (web3.py) can filter and replay them, so they are the normal way
///    to publish "this happened".
///
/// Design rules enforced here (see CLAUDE.md):
///  - Rule 2: executor and WatchDog evidence is never merged. The role is part of the storage
///    key, so the two witnesses occupy different slots and can never overwrite each other.
///  - Rule 3: no raw data on-chain. Only a 32-byte root per step and small metadata.
///  - Rule 8: hashing is keccak256 with OpenZeppelin-compatible sorted-pair Merkle trees,
///    leaf = keccak256(keccak256(chunk)). The scheme id is stored with every commit so a
///    future scheme can be told apart instead of silently replacing this one.
contract EvidenceRegistry {
    /// @notice The two witnesses that may anchor evidence for a step.
    /// @dev An enum is stored as a small integer: Executor = 0, WatchDog = 1.
    enum Role {
        Executor,
        WatchDog
    }

    /// @notice One anchored evidence root.
    /// @param root        Merkle root over the step's chunks (keccak256-oz-sorted-v1).
    /// @param committer   address that sent the transaction (attribution).
    /// @param time        block timestamp in seconds; set by the chain, not the caller.
    /// @param hashScheme  keccak256 of the scheme id string, e.g. "keccak256-oz-sorted-v1".
    struct Commit {
        bytes32 root;
        address committer;
        uint64 time;
        bytes32 hashScheme;
    }

    /// @notice stepKey => commit. `public` makes Solidity generate a free getter
    /// `commits(bytes32)` that off-chain code can call.
    mapping(bytes32 => Commit) public commits;

    /// @notice Emitted once per successful commit.
    /// @dev `indexed` parameters can be filtered efficiently by clients. We index the step key
    /// and the committer so a client can ask "every commit by this agent" or "this step".
    event Committed(
        bytes32 indexed stepKey, Role role, bytes32 root, address indexed committer, bytes32 hashScheme
    );

    error AlreadyCommitted(bytes32 stepKey);
    error EmptyRoot();
    error LengthMismatch();

    // TODO(Phase 2, M2-A): no access control yet — any address may commit for any role.
    // The job contract will bind one executor key and one WatchDog key per job and this
    // registry will then reject commits from an address that is not the assigned agent for
    // that role. Until then, attribution is recorded but not restricted.

    /// @notice Deterministic storage key for a step's evidence.
    /// @dev `pure` means it reads no storage and no chain state, so it is a plain function of
    /// its arguments; Python computes the same value in wdchain/chain/registry.py.
    /// `abi.encode` is the standard, length-prefixed ABI encoding. It is used instead of
    /// `abi.encodePacked` because packed encoding of two dynamic strings is ambiguous:
    /// ("ab","c") and ("a","bc") would pack identically and collide.
    /// The parameters are `memory` so this can be called both from outside (the ABI is the
    /// same either way) and internally from the commit paths below.
    function computeStepKey(string memory sessionId, Role role, string memory stepId)
        public
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(sessionId, role, stepId));
    }

    /// @notice Anchor one step's Merkle root. Write-once.
    /// @dev Reverts if this (session, role, step) was already committed. Anyone may call this
    /// in Phase 1; `msg.sender` is recorded as the committer.
    function commit(
        string calldata sessionId,
        Role role,
        string calldata stepId,
        bytes32 root,
        bytes32 hashScheme
    ) external returns (bytes32 stepKey) {
        stepKey = computeStepKey(sessionId, role, stepId);
        _commit(stepKey, role, root, hashScheme);
    }

    /// @notice Anchor many steps in one transaction.
    /// @dev One transaction per session-role instead of one per step: the per-transaction
    /// overhead (21000 gas) is paid once. Each item is still write-once, and because the whole
    /// transaction reverts on failure, a batch containing an already-committed step commits
    /// nothing. The caller (wdchain-anchor-session) filters out committed steps first.
    /// Arrays are `calldata` (read-only transaction data), which is cheaper than memory.
    function commitBatch(
        string calldata sessionId,
        Role role,
        string[] calldata stepIds,
        bytes32[] calldata roots,
        bytes32 hashScheme
    ) external returns (bytes32[] memory stepKeys) {
        if (stepIds.length != roots.length) revert LengthMismatch();
        stepKeys = new bytes32[](stepIds.length);
        for (uint256 i = 0; i < stepIds.length; i++) {
            bytes32 stepKey = computeStepKey(sessionId, role, stepIds[i]);
            _commit(stepKey, role, roots[i], hashScheme);
            stepKeys[i] = stepKey;
        }
    }

    /// @dev Shared write path. `internal` = callable only from inside this contract.
    function _commit(bytes32 stepKey, Role role, bytes32 root, bytes32 hashScheme) internal {
        if (root == bytes32(0)) revert EmptyRoot();
        // A non-zero committer is the marker that this slot is taken. Reading an unset
        // mapping entry returns an all-zero struct, so this is the standard existence test.
        if (commits[stepKey].committer != address(0)) revert AlreadyCommitted(stepKey);

        commits[stepKey] = Commit({
            root: root,
            committer: msg.sender,
            // block.timestamp is seconds since the Unix epoch, set by the block producer.
            // uint64 is enough until year 584942417355 and packs with the address.
            time: uint64(block.timestamp),
            hashScheme: hashScheme
        });

        emit Committed(stepKey, role, root, msg.sender, hashScheme);
    }

    /// @notice True if this chunk belongs to the step's anchored evidence.
    /// @param chunkDigest keccak256 of the chunk bytes (the content address in the store).
    /// @param proof sibling hashes bottom to top, from wdchain-prove.
    /// @dev This must match wdchain exactly:
    ///   leaf = keccak256(abi.encodePacked(chunkDigest))  == keccak256(chunkDigest)
    ///   node = keccak256(min(a,b) ++ max(a,b))           == MerkleProof's sorted pair
    /// `abi.encodePacked` of a single bytes32 is just those 32 bytes, so this is the double
    /// hash from the scheme. `view` = reads state, changes nothing, free to call off-chain.
    function verifyChunk(bytes32 stepKey, bytes32 chunkDigest, bytes32[] calldata proof)
        external
        view
        returns (bool)
    {
        bytes32 root = commits[stepKey].root;
        if (root == bytes32(0)) return false; // nothing anchored for this step
        bytes32 leaf = keccak256(abi.encodePacked(chunkDigest));
        return MerkleProof.verify(proof, root, leaf);
    }

    /// @notice Convenience read: the whole commit struct for a step.
    function getCommit(string calldata sessionId, Role role, string calldata stepId)
        external
        view
        returns (Commit memory)
    {
        return commits[computeStepKey(sessionId, role, stepId)];
    }

    /// @notice True if this step already has an anchored root (used for idempotent anchoring).
    function isCommitted(bytes32 stepKey) external view returns (bool) {
        return commits[stepKey].committer != address(0);
    }
}
