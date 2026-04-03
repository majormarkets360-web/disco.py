require("@nomiclabs/hardhat-waffle");

module.exports = {
  solidity: "0.8.19",
  networks: {
    hardhat: {},
    mainnet: {
      url: "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY",
      accounts: ["YOUR_PRIVATE_KEY"]
    }
  }
};
