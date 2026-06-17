import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LoginForm } from "@/features/auth/login-form";

// Mock navigation
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

// Mock auth context
const mockLogin = jest.fn();
jest.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({ login: mockLogin }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe("LoginForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders username and password fields", () => {
    render(<LoginForm />);
    expect(screen.getByLabelText("Username")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
  });

  it("renders submit button", () => {
    render(<LoginForm />);
    expect(screen.getByRole("button", { name: /sign in/i })).toBeTruthy();
  });

  it("shows validation error for empty username", async () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(screen.getByText("Username required")).toBeTruthy();
    });
  });

  it("calls login with credentials on submit", async () => {
    mockLogin.mockResolvedValue({ force_change: false });
    render(<LoginForm />);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith({ username: "admin", password: "password123" });
    });
  });
});
