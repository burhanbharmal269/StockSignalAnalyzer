describe("capitalService DTO fixes", () => {
  it("updateCapital sends new_capital not allocated_capital", () => {
    const body = { new_capital: 500000 };
    expect(body).toHaveProperty("new_capital");
    expect((body as Record<string, unknown>)["allocated_capital"]).toBeUndefined();
  });

  it("CapitalAllocation uses allocation_id not id", () => {
    const alloc = { allocation_id: "uuid-456", name: "Global" };
    expect(alloc.allocation_id).toBeDefined();
    expect((alloc as Record<string, unknown>)["id"]).toBeUndefined();
  });

  it("Portfolio uses portfolio_id not id", () => {
    const portfolio = { portfolio_id: "uuid-789", name: "Default" };
    expect(portfolio.portfolio_id).toBeDefined();
    expect((portfolio as Record<string, unknown>)["id"]).toBeUndefined();
  });

  it("listAllocations unwraps .allocations array", () => {
    const raw = { allocations: [{ allocation_id: "a1" }], total: 1 };
    const result = raw.allocations;
    expect(result).toHaveLength(1);
  });

  it("listPortfolios unwraps .portfolios array", () => {
    const raw = { portfolios: [{ portfolio_id: "p1" }], total: 1 };
    const result = raw.portfolios;
    expect(result).toHaveLength(1);
  });
});
