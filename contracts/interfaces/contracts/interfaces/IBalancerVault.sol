// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./IERC20.sol";

interface IBalancerVault {
    function flashLoan(
        address recipient,
        IERC20[] calldata tokens,
        uint256[] calldata amounts,
        bytes calldata userData
    ) external;
    
    function swap(
        SingleSwap calldata singleSwap,
        FundManagement calldata funds,
        uint256 limit,
        uint256 deadline
    ) external returns (uint256);
    
    struct SingleSwap {
        bytes32 poolId;
        uint8 kind;
        IERC20 assetIn;
        IERC20 assetOut;
        uint256 amount;
        bytes userData;
    }
    
    struct FundManagement {
        address sender;
        bool fromInternalBalance;
        address payable recipient;
        bool toInternalBalance;
    }
}
