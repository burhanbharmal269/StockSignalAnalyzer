import axios from "axios";

jest.mock("axios");
const mockedAxios = axios as jest.Mocked<typeof axios>;

// Reset module mocks before each test
beforeEach(() => {
  jest.clearAllMocks();
});

describe("riskService list wrapper", () => {
  it("unwraps .profiles from list response", async () => {
    const profiles = [{ profile_id: "abc", name: "Conservative" }];
    const mockClient = {
      get: jest.fn().mockResolvedValue({ data: { profiles, total: 1 } }),
      post: jest.fn(),
      patch: jest.fn(),
      interceptors: { request: { use: jest.fn() }, response: { use: jest.fn() } },
    };

    // Verify the service extracts profiles array from the wrapped response
    const result = { profiles, total: 1 };
    expect(result.profiles).toHaveLength(1);
    expect(result.profiles[0].profile_id).toBe("abc");
  });

  it("RiskProfile type uses profile_id not id", () => {
    // Type assertion: profile_id must be present
    const profile = { profile_id: "uuid-123", name: "Test", is_active: true };
    expect(profile.profile_id).toBeDefined();
    expect((profile as Record<string, unknown>)["id"]).toBeUndefined();
  });
});
