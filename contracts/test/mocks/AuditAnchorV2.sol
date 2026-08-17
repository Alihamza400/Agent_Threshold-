// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Initializable} from "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";
import {
    Ownable2StepUpgradeable
} from "@openzeppelin-upgradeable/contracts/access/Ownable2StepUpgradeable.sol";

/// @dev V2 mock: mirrors AuditAnchor's storage + views, adds a marker, to
///      prove UUPS upgrades preserve state and add functionality.
contract AuditAnchorV2 is Initializable, Ownable2StepUpgradeable, UUPSUpgradeable {
    mapping(uint256 batchId => bytes32 root) public batchRoots;
    mapping(uint256 batchId => uint256 timestamp) public batchTimestamps;
    uint256 public lastBatchId;
    mapping(address anchor => bool authorized) public isAuthorizedAnchor;
    uint256[50] private __gap;

    uint256 public v2Marker;

    event V2MarkerSet(uint256 value);

    function getBatchRoot(uint256 batchId) external view returns (bytes32) {
        return batchRoots[batchId];
    }

    function setV2Marker(uint256 value) external {
        v2Marker = value;
        emit V2MarkerSet(value);
    }

    function _authorizeUpgrade(address) internal override onlyOwner {}
}
