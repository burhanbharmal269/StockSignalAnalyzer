import { render, screen } from "@testing-library/react";
import { StatusIndicator } from "@/components/shared/status-indicator";

describe("StatusIndicator", () => {
  it("shows healthy label by default for healthy status", () => {
    render(<StatusIndicator status="healthy" />);
    expect(screen.getByText("Healthy")).toBeTruthy();
  });

  it("shows custom label when provided", () => {
    render(<StatusIndicator status="healthy" label="All systems go" />);
    expect(screen.getByText("All systems go")).toBeTruthy();
  });

  it("shows Inactive for inactive status", () => {
    render(<StatusIndicator status="inactive" />);
    expect(screen.getByText("Inactive")).toBeTruthy();
  });

  it("renders a dot", () => {
    const { container } = render(<StatusIndicator status="healthy" />);
    expect(container.querySelector(".rounded-full")).toBeTruthy();
  });
});
