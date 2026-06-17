import { render, screen } from "@testing-library/react";
import { PnLDisplay } from "@/components/shared/pnl-display";

describe("PnLDisplay", () => {
  it("shows + prefix for positive value", () => {
    render(<PnLDisplay value={1000} />);
    const el = screen.getByText(/\+/);
    expect(el).toBeTruthy();
  });

  it("applies profit color for positive", () => {
    const { container } = render(<PnLDisplay value={500} />);
    expect(container.querySelector(".text-profit")).toBeTruthy();
  });

  it("applies loss color for negative", () => {
    const { container } = render(<PnLDisplay value={-500} />);
    expect(container.querySelector(".text-loss")).toBeTruthy();
  });

  it("renders percentage when pct provided", () => {
    render(<PnLDisplay value={500} pct={2.5} />);
    expect(screen.getByText(/\+2\.50%/)).toBeTruthy();
  });
});
