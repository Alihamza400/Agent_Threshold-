// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {BaseTimelockSetup} from "./BaseSetup.t.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {PolicyRegistry} from "../src/PolicyRegistry.sol";
import {PolicyRegistryV2} from "./mocks/PolicyRegistryV2.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

contract PolicyRegistryTest is BaseTimelockSetup {
    PolicyRegistry internal registry;
    address internal writer = makeAddr("policy-writer");
    bytes32 internal agentId = keccak256("agent-01");

    function setUp() public override {
        super.setUp();
        PolicyRegistry impl = new PolicyRegistry();
        bytes memory initData =
            abi.encodeCall(PolicyRegistry.initialize, (address(timelock), writer));
        registry = PolicyRegistry(deployProxy(address(impl), initData));
    }

    // ------------------------------------------------------------- initialize

    function test_initialize_revertsForZeroWriter() public {
        PolicyRegistry impl = new PolicyRegistry();
        vm.expectRevert(PolicyRegistry.ZeroAddress.selector);
        new ERC1967Proxy(
            address(impl),
            abi.encodeCall(PolicyRegistry.initialize, (address(timelock), address(0)))
        );
    }

    function test_implementation_cannotBeReinitialized() public {
        PolicyRegistry impl = new PolicyRegistry();
        vm.expectRevert(); // InvalidInitialization
        impl.initialize(address(timelock), writer);
    }

    // ------------------------------------------------------ recordPolicyUpdate

    function test_recordPolicyUpdate_success() public {
        bytes32 hash = keccak256("policy-v1");
        vm.prank(writer);
        vm.expectEmit(true, true, true, true, address(registry));
        emit PolicyRegistry.PolicyUpdated(agentId, hash, 0);
        registry.recordPolicyUpdate(agentId, hash);
        assertEq(registry.getLatestPolicyHash(agentId), hash);
        assertEq(registry.getPolicyHistory(agentId).length, 1);
    }

    function test_recordPolicyUpdate_nonWriterReverts() public {
        vm.prank(stranger);
        vm.expectRevert(PolicyRegistry.NotPolicyWriter.selector);
        registry.recordPolicyUpdate(agentId, keccak256("x"));
    }

    function test_recordPolicyUpdate_zeroHashReverts() public {
        vm.prank(writer);
        vm.expectRevert(PolicyRegistry.ZeroPolicyHash.selector);
        registry.recordPolicyUpdate(agentId, bytes32(0));
    }

    function test_recordPolicyUpdate_appendOrderPreserved() public {
        vm.startPrank(writer);
        bytes32 h1 = keccak256("v1");
        bytes32 h2 = keccak256("v2");
        bytes32 h3 = keccak256("v3");
        registry.recordPolicyUpdate(agentId, h1);
        registry.recordPolicyUpdate(agentId, h2);
        registry.recordPolicyUpdate(agentId, h3);
        vm.stopPrank();

        bytes32[] memory history = registry.getPolicyHistory(agentId);
        assertEq(history.length, 3);
        assertEq(history[0], h1);
        assertEq(history[1], h2);
        assertEq(history[2], h3);
        assertEq(registry.getLatestPolicyHash(agentId), h3);
    }

    function test_getLatestPolicyHash_emptyIsZero() public {
        assertEq(registry.getLatestPolicyHash(agentId), bytes32(0));
    }

    function test_getPolicyHistory_empty() public {
        assertEq(registry.getPolicyHistory(agentId).length, 0);
    }

    function test_recordPolicyUpdate_isolationBetweenAgents() public {
        bytes32 other = keccak256("agent-02");
        vm.prank(writer);
        registry.recordPolicyUpdate(agentId, keccak256("a"));
        assertEq(registry.getPolicyHistory(other).length, 0);
        assertEq(registry.getLatestPolicyHash(other), bytes32(0));
    }

    // ------------------------------------------------------------ writer role

    function test_setPolicyWriter_viaTimelock() public {
        address newWriter = makeAddr("writer-2");
        runAsOwner(address(registry), abi.encodeCall(PolicyRegistry.setPolicyWriter, (newWriter)));
        assertEq(registry.policyWriter(), newWriter);

        // old writer can no longer record
        vm.prank(writer);
        vm.expectRevert(PolicyRegistry.NotPolicyWriter.selector);
        registry.recordPolicyUpdate(agentId, keccak256("x"));

        // new writer can
        vm.prank(newWriter);
        registry.recordPolicyUpdate(agentId, keccak256("from-new-writer"));
    }

    function test_setPolicyWriter_zeroAddressReverts() public {
        bytes memory call = abi.encodeCall(PolicyRegistry.setPolicyWriter, (address(0)));
        bytes32 salt = scheduleAndWarp(address(registry), call);
        vm.expectRevert(PolicyRegistry.ZeroAddress.selector);
        timelock.execute(address(registry), 0, call, bytes32(0), salt);
    }

    function test_setPolicyWriter_nonOwnerReverts() public {
        vm.prank(attacker);
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, attacker)
        );
        registry.setPolicyWriter(makeAddr("x"));
    }

    function test_setPolicyWriter_lockedByTimelock() public {
        address newWriter = makeAddr("writer-2");
        bytes memory call = abi.encodeCall(PolicyRegistry.setPolicyWriter, (newWriter));
        assertBlockedBeforeDelay(address(registry), call);
        assertEq(registry.policyWriter(), writer); // unchanged before delay elapses
        vm.warp(block.timestamp + 1); // distinct salt for the follow-up
        runAsOwner(address(registry), call);
        assertEq(registry.policyWriter(), newWriter);
    }

    // ------------------------------------------------------------- upgrades

    function test_upgrade_viaTimelock_preservesStorage() public {
        bytes32 h1 = keccak256("v1");
        vm.prank(writer);
        registry.recordPolicyUpdate(agentId, h1);

        PolicyRegistryV2 v2 = new PolicyRegistryV2();
        upgradeViaTimelock(address(registry), address(v2), "");

        assertEq(registry.getLatestPolicyHash(agentId), h1);
        assertEq(registry.policyWriter(), writer);
        assertEq(registry.getPolicyHistory(agentId).length, 1);

        // V2 functionality live; upgrading again exercises V2's _authorizeUpgrade.
        PolicyRegistryV2(address(registry)).setV2Marker(99);
        assertEq(PolicyRegistryV2(address(registry)).v2Marker(), 99);
        PolicyRegistryV2 v3 = new PolicyRegistryV2();
        upgradeViaTimelock(address(registry), address(v3), "");
        assertEq(registry.getLatestPolicyHash(agentId), h1);
    }

    function test_upgrade_nonOwnerReverts() public {
        PolicyRegistryV2 v2 = new PolicyRegistryV2();
        vm.prank(attacker);
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, attacker)
        );
        PolicyRegistry(address(registry)).upgradeToAndCall(address(v2), "");
    }

    function test_ownerIsTimelock() public {
        assertEq(Ownable(address(registry)).owner(), address(timelock));
    }

    // ---------------------------------------------------------------- fuzz

    /// Any number of records append in order; latest is always the last pushed.
    function testFuzz_historyOrder(uint8 count, bytes32 seed) public {
        uint256 n = uint256(count) % 24;
        bytes32[24] memory hashes;
        vm.startPrank(writer);
        for (uint256 i = 0; i < n; i++) {
            bytes32 h = keccak256(abi.encode(seed, i));
            hashes[i] = h;
            registry.recordPolicyUpdate(agentId, h);
        }
        vm.stopPrank();

        bytes32[] memory history = registry.getPolicyHistory(agentId);
        assertEq(history.length, n);
        for (uint256 i = 0; i < n; i++) {
            assertEq(history[i], hashes[i]);
        }
        if (n > 0) assertEq(registry.getLatestPolicyHash(agentId), hashes[n - 1]);
    }

    /// A zero policy hash ALWAYS reverts, regardless of caller or agent.
    function testFuzz_zeroHashAlwaysReverts(bytes32 agentSeed) public {
        vm.prank(writer);
        vm.expectRevert(PolicyRegistry.ZeroPolicyHash.selector);
        registry.recordPolicyUpdate(keccak256(abi.encode("agent", agentSeed)), bytes32(0));
    }
}
