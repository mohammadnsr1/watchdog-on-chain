// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";
import {EvidenceRegistry} from "../EvidenceRegistry.sol";

/// @notice Deploys EvidenceRegistry and records the address for the Python client.
///
/// Run against a local anvil (see README "Phase 1 Part B"):
///
///   forge script contracts/script/DeployEvidenceRegistry.s.sol:DeployEvidenceRegistry \
///       --rpc-url "$WDCHAIN_RPC_URL" --private-key "$WDCHAIN_EXECUTOR_KEY" --broadcast
///
/// Deployment primer: a contract is created by sending a transaction with no recipient whose
/// data is the compiled bytecode. The chain assigns the new contract an address, which is what
/// clients need afterwards. `vm.startBroadcast()` marks the calls that should be sent as real
/// transactions signed by --private-key; everything outside it only runs in the simulator.
contract DeployEvidenceRegistry is Script {
    function run() external {
        vm.startBroadcast();
        EvidenceRegistry registry = new EvidenceRegistry();
        vm.stopBroadcast();

        console.log("EvidenceRegistry deployed");
        console.log("  chainId :", block.chainid);
        console.log("  address :", address(registry));
        console.log("  block   :", block.number);

        // wdchain/chain/config.py reads this file to find the registry.
        string memory json = string.concat(
            '{\n  "chainId": ',
            vm.toString(block.chainid),
            ',\n  "address": "',
            vm.toString(address(registry)),
            '",\n  "deployBlock": ',
            vm.toString(block.number),
            ',\n  "contract": "EvidenceRegistry"\n}\n'
        );
        // Writing needs fs_permissions for ./deployments in foundry.toml.
        vm.writeFile("deployments/anvil.json", json);
        console.log("  wrote   : deployments/anvil.json");
    }
}
