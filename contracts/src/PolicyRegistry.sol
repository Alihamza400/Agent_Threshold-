// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Initializable} from "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";
import {
    Ownable2StepUpgradeable
} from "@openzeppelin-upgradeable/contracts/access/Ownable2StepUpgradeable.sol";

/// @title PolicyRegistry
/// @notice Append-only on-chain history of agent policy hashes (Phase 6, 8.2).
/// @dev Design invariants (audited / fail-closed):
///  - No external calls, no value transfer.
///  - Append-only: entries can only be pushed, never overwritten or deleted.
///  - A single authorized `policyWriter` (backend) records updates; changing
///    the writer is owner-only, hence timelocked (owner = TimelockController).
///  - UUPS upgrades are owner-only (`_authorizeUpgrade`).
contract PolicyRegistry is Initializable, Ownable2StepUpgradeable, UUPSUpgradeable {
    /// @dev agentId => ordered policy-hash history.
    mapping(bytes32 agentId => bytes32[] history) public policyHistory;

    /// @dev Single authorized writer (backend policy service).
    address public policyWriter;

    /// @dev Storage reserved for future upgrades.
    uint256[50] private __gap;

    event PolicyUpdated(bytes32 indexed agentId, bytes32 indexed policyHash, uint256 index);
    event PolicyWriterSet(address indexed writer);

    error NotPolicyWriter();
    error ZeroPolicyHash();
    error ZeroAddress();

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /// @param owner_ Multisig (or TimelockController owned by the multisig).
    /// @param policyWriter_ Initial writer (backend policy service).
    function initialize(address owner_, address policyWriter_) external initializer {
        __Ownable2Step_init();
        if (policyWriter_ == address(0)) revert ZeroAddress();
        _transferOwnership(owner_);
        policyWriter = policyWriter_;
        emit PolicyWriterSet(policyWriter_);
    }

    /// @notice Append a policy hash for an agent. Writer-only; append-only.
    function recordPolicyUpdate(bytes32 agentId, bytes32 policyHash) external {
        if (msg.sender != policyWriter) revert NotPolicyWriter();
        if (policyHash == bytes32(0)) revert ZeroPolicyHash();
        policyHistory[agentId].push(policyHash);
        emit PolicyUpdated(agentId, policyHash, policyHistory[agentId].length - 1);
    }

    /// @notice Latest policy hash for an agent; bytes32(0) if never recorded.
    function getLatestPolicyHash(bytes32 agentId) external view returns (bytes32) {
        bytes32[] storage history = policyHistory[agentId];
        uint256 length = history.length;
        return length == 0 ? bytes32(0) : history[length - 1];
    }

    /// @notice Full ordered policy-hash history for an agent.
    function getPolicyHistory(bytes32 agentId) external view returns (bytes32[] memory) {
        return policyHistory[agentId];
    }

    /// @dev Owner-only (timelocked). Assigning a new writer is recorded as an
    ///      event so admin changes remain auditable on-chain.
    function setPolicyWriter(address writer) external onlyOwner {
        if (writer == address(0)) revert ZeroAddress();
        policyWriter = writer;
        emit PolicyWriterSet(writer);
    }

    /// @dev UUPS: only the owner (timelock in production) may upgrade.
    function _authorizeUpgrade(address newImplementation) internal override onlyOwner {}
}
