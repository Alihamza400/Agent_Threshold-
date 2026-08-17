// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {AuditAnchor} from "../src/AuditAnchor.sol";
import {PolicyRegistry} from "../src/PolicyRegistry.sol";

/// @notice Production deploy: TimelockController -> owner of both contracts,
///         which sit behind UUPS ERC1967 proxies.
/// @dev Required env: PRIVATE_KEY, ANCHOR_SERVICE, POLICY_SERVICE.
///      Optional: MULTISIG (defaults to deployer), TIMELOCK_DELAY (48h).
contract Deploy is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerKey);
        address multisig = vm.envOr("MULTISIG", deployer);
        address anchorService = vm.envAddress("ANCHOR_SERVICE");
        address policyService = vm.envAddress("POLICY_SERVICE");
        uint256 delay = vm.envOr("TIMELOCK_DELAY", uint256(48 hours));

        vm.startBroadcast(deployerKey);

        address[] memory proposers = new address[](1);
        proposers[0] = multisig;
        address[] memory executors = new address[](1);
        executors[0] = multisig;
        TimelockController timelock = new TimelockController(delay, proposers, executors, multisig);

        AuditAnchor anchorImpl = new AuditAnchor();
        AuditAnchor anchor = AuditAnchor(
            address(
                new ERC1967Proxy(
                    address(anchorImpl),
                    abi.encodeCall(AuditAnchor.initialize, (address(timelock), anchorService))
                )
            )
        );

        PolicyRegistry registryImpl = new PolicyRegistry();
        PolicyRegistry registry = PolicyRegistry(
            address(
                new ERC1967Proxy(
                    address(registryImpl),
                    abi.encodeCall(PolicyRegistry.initialize, (address(timelock), policyService))
                )
            )
        );

        vm.stopBroadcast();

        console2.log("TimelockController", address(timelock));
        console2.log("AuditAnchor proxy", address(anchor));
        console2.log("AuditAnchor impl", address(anchorImpl));
        console2.log("PolicyRegistry proxy", address(registry));
        console2.log("PolicyRegistry impl", address(registryImpl));
        console2.log("owner", address(timelock));
        console2.log("authorizedAnchor", anchorService);
        console2.log("policyWriter", policyService);
    }
}
