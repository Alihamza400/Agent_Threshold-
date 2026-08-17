// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

/// @dev Cross-language fixture: the SAME leaves must produce the SAME root in
///      Solidity and in the Python audit-service (`audit_service.merkle`).
///      Fixture root (keccak256 leaves "leaf0".."leaf4", padded odd-last):
///      0xb0cb5b3f0776b1932410c3ffbb811f62a8f26a361d22b818e4e92965a6014da5
///      Test is dual-locked: recomputing here AND the Python test both assert
///      the literal above, so a drift on either side breaks the build.
contract MerkleCrossCheckTest is Test {
    function test_merkleRoot_matchesPythonFixture() public {
        bytes32[] memory leaves = new bytes32[](5);
        for (uint256 i = 0; i < 5; i++) {
            leaves[i] = keccak256(abi.encodePacked("leaf", _uintToString(i)));
        }
        assertEq(computeRoot(leaves), 0xb0cb5b3f0776b1932410c3ffbb811f62a8f26a361d22b818e4e92965a6014da5);
    }

    /// @dev Mirror of `audit_service.merkle.merkle_root` (odd last duplicated).
    function computeRoot(bytes32[] memory leaves) internal pure returns (bytes32) {
        require(leaves.length > 0, "empty tree");
        bytes32[] memory level = leaves;
        while (level.length > 1) {
            bytes32[] memory padded = level.length % 2 == 1
                ? _concat(level, level[level.length - 1])
                : level;
            bytes32[] memory next = new bytes32[](padded.length / 2);
            for (uint256 i = 0; i < next.length; i++) {
                next[i] = keccak256(abi.encodePacked(padded[2 * i], padded[2 * i + 1]));
            }
            level = next;
        }
        return level[0];
    }

    function _concat(bytes32[] memory arr, bytes32 last) internal pure returns (bytes32[] memory) {
        bytes32[] memory out = new bytes32[](arr.length + 1);
        for (uint256 i = 0; i < arr.length; i++) {
            out[i] = arr[i];
        }
        out[arr.length] = last;
        return out;
    }

    function _uintToString(uint256 value) internal pure returns (string memory) {
        if (value == 0) return "0";
        uint256 n = value;
        uint256 digits;
        while (n > 0) {
            digits++;
            n /= 10;
        }
        bytes memory buf = new bytes(digits);
        while (value > 0) {
            digits--;
            buf[digits] = bytes1(uint8(48 + (value % 10)));
            value /= 10;
        }
        return string(buf);
    }
}