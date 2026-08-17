// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

/// @dev Shared harness: every admin action must traverse a 48h timelock, and
///      the contracts are deployed behind UUPS proxies. The test contract is
///      both proposer and executor (production uses a multisig).
abstract contract BaseTimelockSetup is Test {
    uint256 internal constant TIMELOCK_DELAY = 48 hours;

    TimelockController internal timelock;
    address internal attacker = makeAddr("attacker");
    address internal stranger = makeAddr("stranger");

    function setUp() public virtual {
        address[] memory proposers = new address[](1);
        proposers[0] = address(this);
        address[] memory executors = new address[](1);
        executors[0] = address(this);
        timelock = new TimelockController(
            TIMELOCK_DELAY,
            proposers,
            executors,
            address(this) // admin -> test contract manages roles
        );
    }

    /// @dev Deploy an ERC1967 proxy for an upgradeable implementation.
    function deployProxy(address impl, bytes memory initData) internal returns (address) {
        return address(new ERC1967Proxy(impl, initData));
    }

    /// @dev Schedule an owner call in the timelock and warp past the 48h delay.
    function scheduleAndWarp(address target, bytes memory data) internal returns (bytes32 salt) {
        salt = keccak256(abi.encode(target, data, block.timestamp));
        timelock.schedule(target, 0, data, bytes32(0), salt, TIMELOCK_DELAY);
        vm.warp(block.timestamp + TIMELOCK_DELAY + 1);
    }

    /// @dev Execute an owner-only call through the 48h timelock.
    function runAsOwner(address target, bytes memory data) internal {
        bytes32 salt = scheduleAndWarp(target, data);
        timelock.execute(target, 0, data, bytes32(0), salt);
    }

    /// @dev Assert an owner-only call CANNOT execute before the delay elapses.
    function assertBlockedBeforeDelay(address target, bytes memory data) internal {
        bytes32 salt = keccak256(abi.encode(target, data, block.timestamp));
        timelock.schedule(target, 0, data, bytes32(0), salt, TIMELOCK_DELAY);
        vm.expectRevert(); // TimelockController: operation is not ready
        timelock.execute(target, 0, data, bytes32(0), salt);
    }

    /// @dev Upgrade a UUPS proxy through the timelock.
    function upgradeViaTimelock(address proxy, address newImpl, bytes memory data) internal {
        bytes memory call = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (newImpl, data));
        runAsOwner(proxy, call);
    }
}
