// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Initializable} from "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";
import {
    Ownable2StepUpgradeable
} from "@openzeppelin-upgradeable/contracts/access/Ownable2StepUpgradeable.sol";

/// @title AuditAnchor
/// @notice Append-only on-chain anchor for audit-log Merkle roots (Phase 6, 8.1).
/// @dev Design invariants (audited / fail-closed):
///  - No external calls, no value transfer: minimal attack surface.
///  - batchId is strictly increasing; duplicates always revert (idempotent).
///  - Only authorized anchors may submit; the set is owner-managed.
///  - Owner is a 48h TimelockController in production, so every admin action
///    (including UUPS upgrades via `_authorizeUpgrade`) is timelocked.
///  - History is append-only: once a batch is anchored it can never be
///    overwritten or deleted.
contract AuditAnchor is Initializable, Ownable2StepUpgradeable, UUPSUpgradeable {
    /// @dev Merkle root for each anchored batch.
    mapping(uint256 batchId => bytes32 root) public batchRoots;

    /// @dev Block timestamp when each batch was anchored.
    mapping(uint256 batchId => uint256 timestamp) public batchTimestamps;

    /// @dev Highest anchored batch id. The next valid id is `lastBatchId + 1`.
    uint256 public lastBatchId;

    /// @dev Authorized submitter set (backend anchor service addresses).
    mapping(address anchor => bool authorized) public isAuthorizedAnchor;

    /// @dev Storage reserved for future upgrades.
    uint256[50] private __gap;

    event BatchAnchored(uint256 indexed batchId, bytes32 indexed merkleRoot, uint256 timestamp);
    event AuthorizedAnchorAdded(address indexed anchor);
    event AuthorizedAnchorRemoved(address indexed anchor);

    error ZeroMerkleRoot();
    error BatchAlreadyAnchored(uint256 batchId);
    error BatchIdNotStrictlyIncreasing(uint256 expectedNext, uint256 given);
    error NotAuthorizedAnchor();
    error ZeroAddress();

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /// @param owner_ Multisig (or TimelockController owned by the multisig).
    /// @param authorizedAnchor_ Initial anchor submitter (backend service).
    function initialize(address owner_, address authorizedAnchor_) external initializer {
        __Ownable2Step_init();
        if (authorizedAnchor_ == address(0)) revert ZeroAddress();
        _transferOwnership(owner_);
        isAuthorizedAnchor[authorizedAnchor_] = true;
        emit AuthorizedAnchorAdded(authorizedAnchor_);
    }

    /// @notice Anchor a new audit batch root. batchId must equal lastBatchId + 1.
    /// @dev Strictly-increasing id makes duplicate submission impossible;
    ///      the explicit duplicate check is defense-in-depth.
    function anchorBatch(uint256 batchId, bytes32 merkleRoot) external {
        if (!isAuthorizedAnchor[msg.sender]) revert NotAuthorizedAnchor();
        if (merkleRoot == bytes32(0)) revert ZeroMerkleRoot();
        if (batchId != lastBatchId + 1) {
            if (batchRoots[batchId] != bytes32(0)) revert BatchAlreadyAnchored(batchId);
            revert BatchIdNotStrictlyIncreasing(lastBatchId + 1, batchId);
        }
        batchRoots[batchId] = merkleRoot;
        batchTimestamps[batchId] = block.timestamp;
        lastBatchId = batchId;
        emit BatchAnchored(batchId, merkleRoot, block.timestamp);
    }

    /// @notice Read the anchored root for a batch (zero if never anchored).
    function getBatchRoot(uint256 batchId) external view returns (bytes32) {
        return batchRoots[batchId];
    }

    function addAuthorizedAnchor(address anchor) external onlyOwner {
        if (anchor == address(0)) revert ZeroAddress();
        isAuthorizedAnchor[anchor] = true;
        emit AuthorizedAnchorAdded(anchor);
    }

    function removeAuthorizedAnchor(address anchor) external onlyOwner {
        if (isAuthorizedAnchor[anchor]) {
            isAuthorizedAnchor[anchor] = false;
            emit AuthorizedAnchorRemoved(anchor);
        }
    }

    /// @dev UUPS: only the owner (timelock in production) may upgrade.
    function _authorizeUpgrade(address newImplementation) internal override onlyOwner {}
}
