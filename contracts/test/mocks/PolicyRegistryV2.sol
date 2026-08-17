// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Initializable} from "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";
import {
    Ownable2StepUpgradeable
} from "@openzeppelin-upgradeable/contracts/access/Ownable2StepUpgradeable.sol";

/// @dev V2 mock: mirrors PolicyRegistry's storage + views, adds a marker, to
///      prove UUPS upgrades preserve state and add functionality.
contract PolicyRegistryV2 is Initializable, Ownable2StepUpgradeable, UUPSUpgradeable {
    mapping(bytes32 agentId => bytes32[] history) public policyHistory;
    address public policyWriter;
    uint256[50] private __gap;

    uint256 public v2Marker;

    function getLatestPolicyHash(bytes32 agentId) external view returns (bytes32) {
        bytes32[] storage history = policyHistory[agentId];
        uint256 length = history.length;
        return length == 0 ? bytes32(0) : history[length - 1];
    }

    function getPolicyHistory(bytes32 agentId) external view returns (bytes32[] memory) {
        return policyHistory[agentId];
    }

    function setV2Marker(uint256 value) external {
        v2Marker = value;
    }

    function _authorizeUpgrade(address) internal override onlyOwner {}
}
