// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// forge-std is Foundry's test library, installed into lib/ with the other dependencies.
// `Test` gives assertions (assertEq, assertTrue), cheatcodes (vm.*) and console logging.
import {Test, console} from "forge-std/Test.sol";
import {EvidenceRegistry} from "../EvidenceRegistry.sol";

/// @notice Tests for the evidence anchor.
///
/// Foundry runs every function named `test*` as its own transaction against a fresh copy of
/// the state produced by `setUp()`. Cheatcodes used here:
///   vm.prank(addr)       next call comes from `addr` (simulates another agent's key)
///   vm.expectRevert(..)  the next call must revert with this error
///   vm.expectEmit(...)   the next call must emit this exact event
///   vm.readFile(path)    read a file (allowed only for paths in foundry.toml fs_permissions)
///   vm.parseJson*        decode JSON into Solidity values
contract EvidenceRegistryTest is Test {
    EvidenceRegistry registry;

    // Two distinct addresses standing in for the two independent witnesses. In a real run
    // these are separate keys held by separate organizations.
    address executorAgent = address(0xE0);
    address watchdogAgent = address(0xDD);

    string constant SESSION = "20261007T205057Z";
    bytes32 constant SCHEME = keccak256("keccak256-oz-sorted-v1");
    bytes32 constant ROOT_A = bytes32(uint256(0xA1));
    bytes32 constant ROOT_B = bytes32(uint256(0xB2));

    // Must match the contract's event signature exactly for vm.expectEmit.
    event Committed(
        bytes32 indexed stepKey, EvidenceRegistry.Role role, bytes32 root, address indexed committer, bytes32 hashScheme
    );

    function setUp() public {
        registry = new EvidenceRegistry();
    }

    // --- basic commit -----------------------------------------------------------------

    function test_CommitStoresRootCommitterAndTime() public {
        // Make block.timestamp a known value so the assertion is not tied to the clock.
        vm.warp(1_800_000_000);

        vm.prank(executorAgent);
        bytes32 stepKey = registry.commit(SESSION, EvidenceRegistry.Role.Executor, "w000000", ROOT_A, SCHEME);

        (bytes32 root, address committer, uint64 time, bytes32 scheme) = registry.commits(stepKey);
        assertEq(root, ROOT_A, "root");
        assertEq(committer, executorAgent, "committer is msg.sender, not an argument");
        assertEq(time, uint64(1_800_000_000), "time comes from the block");
        assertEq(scheme, SCHEME, "hash scheme id");
        assertTrue(registry.isCommitted(stepKey));
    }

    function test_CommitEmitsEvent() public {
        bytes32 expectedKey = registry.computeStepKey(SESSION, EvidenceRegistry.Role.WatchDog, "w000003");

        // Check both indexed topics and the unindexed data of the next emitted event.
        vm.expectEmit(true, true, false, true);
        emit Committed(expectedKey, EvidenceRegistry.Role.WatchDog, ROOT_B, watchdogAgent, SCHEME);

        vm.prank(watchdogAgent);
        registry.commit(SESSION, EvidenceRegistry.Role.WatchDog, "w000003", ROOT_B, SCHEME);
    }

    function test_SecondCommitToSameStepKeyReverts() public {
        vm.prank(executorAgent);
        bytes32 stepKey = registry.commit(SESSION, EvidenceRegistry.Role.Executor, "w000000", ROOT_A, SCHEME);

        // Write-once: even the original committer cannot replace an anchored root.
        vm.expectRevert(abi.encodeWithSelector(EvidenceRegistry.AlreadyCommitted.selector, stepKey));
        vm.prank(executorAgent);
        registry.commit(SESSION, EvidenceRegistry.Role.Executor, "w000000", ROOT_B, SCHEME);

        // ... and neither can anybody else.
        vm.expectRevert(abi.encodeWithSelector(EvidenceRegistry.AlreadyCommitted.selector, stepKey));
        vm.prank(watchdogAgent);
        registry.commit(SESSION, EvidenceRegistry.Role.Executor, "w000000", ROOT_B, SCHEME);

        (bytes32 root,,,) = registry.commits(stepKey);
        assertEq(root, ROOT_A, "original root survives");
    }

    function test_EmptyRootReverts() public {
        vm.expectRevert(EvidenceRegistry.EmptyRoot.selector);
        registry.commit(SESSION, EvidenceRegistry.Role.Executor, "w000000", bytes32(0), SCHEME);
    }

    // --- rule 2: the two witnesses never collide ---------------------------------------

    function test_ExecutorAndWatchdogCommitsForSameStepCoexist() public {
        vm.prank(executorAgent);
        bytes32 keyE = registry.commit(SESSION, EvidenceRegistry.Role.Executor, "w000000", ROOT_A, SCHEME);
        vm.prank(watchdogAgent);
        bytes32 keyW = registry.commit(SESSION, EvidenceRegistry.Role.WatchDog, "w000000", ROOT_B, SCHEME);

        assertTrue(keyE != keyW, "role is part of the key");

        (bytes32 rootE, address committerE,,) = registry.commits(keyE);
        (bytes32 rootW, address committerW,,) = registry.commits(keyW);
        assertEq(rootE, ROOT_A);
        assertEq(rootW, ROOT_B);
        assertEq(committerE, executorAgent);
        assertEq(committerW, watchdogAgent);
    }

    // --- step key ----------------------------------------------------------------------

    function test_ComputeStepKeyMatchesAbiEncode() public view {
        bytes32 expected = keccak256(abi.encode(SESSION, EvidenceRegistry.Role.WatchDog, "w000012"));
        assertEq(registry.computeStepKey(SESSION, EvidenceRegistry.Role.WatchDog, "w000012"), expected);
    }

    function test_StepKeyIsNotAmbiguousAcrossStringBoundaries() public view {
        // abi.encode is length-prefixed, so these two must differ. (With abi.encodePacked
        // they would be identical and two different steps would share one storage slot.)
        bytes32 a = registry.computeStepKey("ab", EvidenceRegistry.Role.Executor, "c");
        bytes32 b = registry.computeStepKey("a", EvidenceRegistry.Role.Executor, "bc");
        assertTrue(a != b, "step keys must not collide across string boundaries");
    }

    // --- batch -------------------------------------------------------------------------

    function test_CommitBatchStoresEveryItem() public {
        string[] memory stepIds = new string[](3);
        bytes32[] memory roots = new bytes32[](3);
        for (uint256 i = 0; i < 3; i++) {
            stepIds[i] = string.concat("w00000", vm.toString(i));
            roots[i] = keccak256(abi.encodePacked("root", i));
        }

        vm.prank(executorAgent);
        bytes32[] memory keys = registry.commitBatch(SESSION, EvidenceRegistry.Role.Executor, stepIds, roots, SCHEME);

        for (uint256 i = 0; i < 3; i++) {
            (bytes32 root, address committer,,) = registry.commits(keys[i]);
            assertEq(root, roots[i]);
            assertEq(committer, executorAgent);
            assertEq(keys[i], registry.computeStepKey(SESSION, EvidenceRegistry.Role.Executor, stepIds[i]));
        }
    }

    function test_CommitBatchIsWriteOncePerItem() public {
        string[] memory stepIds = new string[](2);
        stepIds[0] = "w000000";
        stepIds[1] = "w000001";
        bytes32[] memory roots = new bytes32[](2);
        roots[0] = ROOT_A;
        roots[1] = ROOT_B;

        // Commit the second step on its own first.
        vm.prank(executorAgent);
        registry.commit(SESSION, EvidenceRegistry.Role.Executor, "w000001", ROOT_B, SCHEME);

        // The batch now contains one already-committed item, so the whole transaction reverts
        // and nothing in it is written (atomicity).
        bytes32 clashKey = registry.computeStepKey(SESSION, EvidenceRegistry.Role.Executor, "w000001");
        vm.expectRevert(abi.encodeWithSelector(EvidenceRegistry.AlreadyCommitted.selector, clashKey));
        vm.prank(executorAgent);
        registry.commitBatch(SESSION, EvidenceRegistry.Role.Executor, stepIds, roots, SCHEME);

        bytes32 firstKey = registry.computeStepKey(SESSION, EvidenceRegistry.Role.Executor, "w000000");
        assertFalse(registry.isCommitted(firstKey), "reverted batch wrote nothing");
    }

    function test_CommitBatchLengthMismatchReverts() public {
        string[] memory stepIds = new string[](2);
        stepIds[0] = "w000000";
        stepIds[1] = "w000001";
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = ROOT_A;

        vm.expectRevert(EvidenceRegistry.LengthMismatch.selector);
        registry.commitBatch(SESSION, EvidenceRegistry.Role.Executor, stepIds, roots, SCHEME);
    }

    // --- cross-language compatibility with wdchain --------------------------------------

    /// @notice The scheme check that matters: a tree built in Python verifies in Solidity.
    /// The fixture is written by `python3 scripts/make_merkle_fixture.py` before `forge test`.
    function test_PythonFixtureVerifiesOnChain() public {
        string memory json = vm.readFile("fixtures/merkle_fixture.json");

        bytes32 root = vm.parseJsonBytes32(json, ".root");
        uint256 n = vm.parseJsonUint(json, ".n_chunks");
        assertGt(n, 1, "fixture should have several chunks");

        vm.prank(watchdogAgent);
        bytes32 stepKey = registry.commit(SESSION, EvidenceRegistry.Role.WatchDog, "fixture", root, SCHEME);

        for (uint256 i = 0; i < n; i++) {
            string memory base = string.concat(".chunks[", vm.toString(i), "]");
            bytes32 digest = vm.parseJsonBytes32(json, string.concat(base, ".digest"));
            bytes32[] memory proof = vm.parseJsonBytes32Array(json, string.concat(base, ".proof"));

            assertTrue(registry.verifyChunk(stepKey, digest, proof), "every chunk must verify");

            // A chunk that was never committed must fail, even with a valid-looking proof.
            bytes32 tamperedDigest = bytes32(uint256(digest) ^ 1);
            assertFalse(registry.verifyChunk(stepKey, tamperedDigest, proof), "tampered digest must fail");

            // Flipping one bit of one sibling must break the path to the root.
            if (proof.length > 0) {
                bytes32[] memory tamperedProof = proof;
                tamperedProof[0] = bytes32(uint256(proof[0]) ^ 1);
                assertFalse(registry.verifyChunk(stepKey, digest, tamperedProof), "tampered proof must fail");
            }
        }
    }

    function test_VerifyChunkFalseForUncommittedStep() public view {
        bytes32 unknownKey = registry.computeStepKey(SESSION, EvidenceRegistry.Role.Executor, "never-committed");
        bytes32[] memory emptyProof = new bytes32[](0);
        assertFalse(registry.verifyChunk(unknownKey, keccak256("x"), emptyProof));
    }

    // --- gas (a paper metric) ------------------------------------------------------------

    /// @notice Prints gas for single and batched commits. Run with `forge test -vv` to see it.
    /// @dev Gas is the unit of work on an EVM chain; each committed step costs roughly one
    /// 32-byte storage write plus its share of the ~21000 gas per-transaction overhead.
    function test_LogGasForCommitAndBatch() public {
        uint256 before = gasleft(); // gasleft() is the gas remaining in this call
        registry.commit(SESSION, EvidenceRegistry.Role.Executor, "gas-single", ROOT_A, SCHEME);
        console.log("gas commit(1 step)        :", before - gasleft());

        uint256[3] memory sizes = [uint256(1), 10, 100];
        for (uint256 s = 0; s < sizes.length; s++) {
            uint256 n = sizes[s];
            string[] memory stepIds = new string[](n);
            bytes32[] memory roots = new bytes32[](n);
            for (uint256 i = 0; i < n; i++) {
                // Unique per batch size so the batches do not collide with each other.
                stepIds[i] = string.concat("gas-", vm.toString(n), "-", vm.toString(i));
                roots[i] = keccak256(abi.encodePacked(n, i));
            }
            uint256 g0 = gasleft();
            registry.commitBatch(SESSION, EvidenceRegistry.Role.WatchDog, stepIds, roots, SCHEME);
            uint256 used = g0 - gasleft();
            console.log("gas commitBatch steps     :", n);
            console.log("   total                  :", used);
            console.log("   per step               :", used / n);
        }
    }
}
