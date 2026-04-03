async function main() {
    const MultiDEXArbitrage = await ethers.getContractFactory("MultiDEXArbitrage");
    const contract = await MultiDEXArbitrage.deploy();
    await contract.deployed();
    console.log("Contract deployed to:", contract.address);
}

main().catch(console.error);
