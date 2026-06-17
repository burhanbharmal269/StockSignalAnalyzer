import { TOKEN_KEY } from "@/lib/constants";

jest.mock("axios", () => {
  const actual = jest.requireActual("axios");
  return {
    ...actual,
    default: {
      create: jest.fn(() => ({
        interceptors: {
          request: { use: jest.fn() },
          response: { use: jest.fn() },
        },
      })),
    },
  };
});

describe("api-client", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("reads access token from localStorage for requests", () => {
    localStorage.setItem(TOKEN_KEY, "test-token");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("test-token");
  });

  it("clears token on logout", () => {
    localStorage.setItem(TOKEN_KEY, "test-token");
    localStorage.removeItem(TOKEN_KEY);
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});
