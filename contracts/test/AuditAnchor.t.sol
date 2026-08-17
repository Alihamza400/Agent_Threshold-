// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {BaseTimelockSetup} from "./BaseSetup.t.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {AuditAnchor} from "../src/AuditAnchor.sol";
import {AuditAnchorV2} from "./mocks/AuditAnchorV2.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

contract AuditAnchorTest is BaseTimelockSetup {
    AuditAnchor internal anchor;
    address internal authorizedAnchor = makeAddr("anchor-service");

    function setUp() public override {
        super.setUp();
        AuditAnchor impl = new AuditAnchor();
        bytes memory initData =
            abi.encodeCall(AuditAnchor.initialize, (address(timelock), authorizedAnchor));
        anchor = AuditAnchor(deployProxy(address(impl), initData));
    }

    // ------------------------------------------------------------- initialize

    function test_initialize_revertsForZeroAuthorizedAnchor() public {
        AuditAnchor impl = new AuditAnchor();
        vm.expectRevert(AuditAnchor.ZeroAddress.selector);
        new ERC1967Proxy(
            address(impl), abi.encodeCall(AuditAnchor.initialize, (address(timelock), address(0)))
        );
    }

    function test_implementation_cannotBeReinitialized() public {
        AuditAnchor impl = new AuditAnchor();
        vm.expectRevert(); // InvalidInitialization
        impl.initialize(address(timelock), authorizedAnchor);
    }

    // ------------------------------------------------------------ anchorBatch

    function test_anchorBatch_success() public {
        bytes32 root = keccak256("batch-1");
        vm.prank(authorizedAnchor);
        vm.expectEmit(true, true, true, true, address(anchor));
        emit AuditAnchor.BatchAnchored(1, root, block.timestamp);
        anchor.anchorBatch(1, root);
        assertEq(anchor.lastBatchId(), 1);
        assertEq(anchor.getBatchRoot(1), root);
    }

    function test_anchorBatch_unauthorizedReverts() public {
        vm.prank(stranger);
        vm.expectRevert(AuditAnchor.NotAuthorizedAnchor.selector);
        anchor.anchorBatch(1, keccak256("x"));
    }

    function test_anchorBatch_zeroRootReverts() public {
        vm.prank(authorizedAnchor);
        vm.expectRevert(AuditAnchor.ZeroMerkleRoot.selector);
        anchor.anchorBatch(1, bytes32(0));
    }

    function test_anchorBatch_skippedIdReverts() public {
        vm.startPrank(authorizedAnchor);
        anchor.anchorBatch(1, keccak256("1"));
        vm.expectRevert(
            abi.encodeWithSelector(AuditAnchor.BatchIdNotStrictlyIncreasing.selector, 2, 3)
        );
        anchor.anchorBatch(3, keccak256("3"));
        vm.stopPrank();
    }

    function test_anchorBatch_duplicateReverts() public {
        vm.startPrank(authorizedAnchor);
        anchor.anchorBatch(1, keccak256("1"));
        vm.expectRevert(abi.encodeWithSelector(AuditAnchor.BatchAlreadyAnchored.selector, 1));
        anchor.anchorBatch(1, keccak256("1-again"));
        vm.stopPrank();
    }

    function test_anchorBatch_sequentialIds() public {
        vm.startPrank(authorizedAnchor);
        for (uint256 i = 1; i <= 5; i++) {
            anchor.anchorBatch(i, keccak256(abi.encode(i)));
        }
        vm.stopPrank();
        assertEq(anchor.lastBatchId(), 5);
        assertEq(anchor.getBatchRoot(4), keccak256(abi.encode(4)));
    }

    function test_getBatchRoot_unanchoredIsZero() public {
        assertEq(anchor.getBatchRoot(999), bytes32(0));
    }

    function test_anchor_removedAnchorCannotSubmit() public {
        runAsOwner(
            address(anchor), abi.encodeCall(AuditAnchor.removeAuthorizedAnchor, (authorizedAnchor))
        );
        assertEq(anchor.isAuthorizedAnchor(authorizedAnchor), false);
        vm.prank(authorizedAnchor);
        vm.expectRevert(AuditAnchor.NotAuthorizedAnchor.selector);
        anchor.anchorBatch(1, keccak256("x"));
    }

    // --------------------------------------------------- authorized anchors

    function test_addAuthorizedAnchor_viaTimelock() public {
        address second = makeAddr("anchor-2");
        runAsOwner(address(anchor), abi.encodeCall(AuditAnchor.addAuthorizedAnchor, (second)));
        assertEq(anchor.isAuthorizedAnchor(second), true);
        vm.prank(second);
        anchor.anchorBatch(1, keccak256("from-second"));
    }

    function test_addAuthorizedAnchor_zeroAddressReverts() public {
        bytes memory call = abi.encodeCall(AuditAnchor.addAuthorizedAnchor, (address(0)));
        bytes32 salt = scheduleAndWarp(address(anchor), call);
        vm.expectRevert(AuditAnchor.ZeroAddress.selector);
        timelock.execute(address(anchor), 0, call, bytes32(0), salt);
    }

    function test_addAuthorizedAnchor_nonOwnerReverts() public {
        vm.prank(attacker);
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, attacker)
        );
        anchor.addAuthorizedAnchor(makeAddr("x"));
    }

    function test_removeAuthorizedAnchor_nonMemberIsNoOp() public {
        address ghost = makeAddr("ghost");
        runAsOwner(address(anchor), abi.encodeCall(AuditAnchor.removeAuthorizedAnchor, (ghost)));
        assertEq(anchor.isAuthorizedAnchor(ghost), false);
    }

    function test_removeAuthorizedAnchor_removalLockedByTimelock() public {
        bytes memory call = abi.encodeCall(AuditAnchor.removeAuthorizedAnchor, (authorizedAnchor));
        assertBlockedBeforeDelay(address(anchor), call);
        // still authorized until the timelock executes
        assertEq(anchor.isAuthorizedAnchor(authorizedAnchor), true);
        vm.warp(block.timestamp + 1); // distinct salt for the follow-up
        runAsOwner(address(anchor), call);
        assertEq(anchor.isAuthorizedAnchor(authorizedAnchor), false);
    }

    // ------------------------------------------------------------- upgrades

    function test_upgrade_viaTimelock_preservesStorage() public {
        bytes32 root = keccak256("pre-upgrade");
        vm.prank(authorizedAnchor);
        anchor.anchorBatch(1, root);

        AuditAnchorV2 v2 = new AuditAnchorV2();
        upgradeViaTimelock(address(anchor), address(v2), "");

        // Storage preserved across the UUPS upgrade.
        assertEq(anchor.getBatchRoot(1), root);
        assertEq(anchor.lastBatchId(), 1);
        assertEq(anchor.isAuthorizedAnchor(authorizedAnchor), true);

        // New v2 functionality live at the same proxy.
        vm.expectEmit(true, true, true, true, address(anchor));
        emit AuditAnchorV2.V2MarkerSet(42);
        AuditAnchorV2(address(anchor)).setV2Marker(42);
        assertEq(AuditAnchorV2(address(anchor)).v2Marker(), 42);

        // Upgrading again exercises V2's own _authorizeUpgrade (owner-only).
        AuditAnchorV2 v3 = new AuditAnchorV2();
        upgradeViaTimelock(address(anchor), address(v3), "");
        AuditAnchorV2(address(anchor)).setV2Marker(7);
        assertEq(AuditAnchorV2(address(anchor)).v2Marker(), 7);
    }

    function test_upgrade_nonOwnerReverts() public {
        AuditAnchorV2 v2 = new AuditAnchorV2();
        vm.prank(attacker);
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, attacker)
        );
        AuditAnchor(address(anchor)).upgradeToAndCall(address(v2), "");
    }

    function test_ownerIsTimelock() public {
        assertEq(Ownable(address(anchor)).owner(), address(timelock));
    }

    // ---------------------------------------------------------------- fuzz

    /// Duplicate batch anchoring can NEVER succeed, no matter the inputs.
    function testFuzz_duplicateAnchoringAlwaysReverts(uint8 skip, bytes32 root) public {
        uint256 n = 2 + (uint256(skip) % 8);
        vm.startPrank(authorizedAnchor);
        for (uint256 i = 1; i <= n; i++) {
            anchor.anchorBatch(i, keccak256(abi.encode("r", i)));
        }
        uint256 batchId = 1 + (uint256(root) % n);
        vm.expectRevert(); // BatchAlreadyAnchored
        anchor.anchorBatch(batchId, root);
        vm.stopPrank();
    }

    /// After batch 1, only batch 2 is accepted; every other id must revert.
    function testFuzz_skippedIdAlwaysReverts(uint256 batchId, bytes32 root) public {
        vm.assume(batchId != 0);
        vm.prank(authorizedAnchor);
        anchor.anchorBatch(1, keccak256("one"));
        if (batchId == 2) {
            vm.prank(authorizedAnchor);
            anchor.anchorBatch(2, root); // next id accepted
            assertEq(anchor.getBatchRoot(2), root);
            return;
        }
        vm.prank(authorizedAnchor);
        vm.expectRevert(); // NotStrictlyIncreasing or AlreadyAnchored
        anchor.anchorBatch(batchId, root);
    }

    /// Sequential batches 1..n always succeed and store the exact root.
    function testFuzz_sequentialBatchRoots(uint8 n, bytes32 seed) public {
        uint256 count = uint256(n) % 12;
        vm.startPrank(authorizedAnchor);
        for (uint256 i = 1; i <= count; i++) {
            bytes32 root = keccak256(abi.encode(seed, i));
            anchor.anchorBatch(i, root);
            assertEq(anchor.getBatchRoot(i), root);
        }
        vm.stopPrank();
        assertEq(anchor.lastBatchId(), count);
    }
}
