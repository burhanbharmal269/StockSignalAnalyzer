import { render, screen } from "@testing-library/react";
import { TradingModeBadge } from "@/components/shared/trading-mode-badge";

describe("TradingModeBadge", () => {
  it("renders LIVE text for LIVE mode", () => {
    render(<TradingModeBadge mode="LIVE" />);
    expect(screen.getByText("LIVE")).toBeTruthy();
  });

  it("renders PAPER text for PAPER mode", () => {
    render(<TradingModeBadge mode="PAPER" />);
    expect(screen.getByText("PAPER")).toBeTruthy();
  });

  it("applies profit color for LIVE mode", () => {
    const { container } = render(<TradingModeBadge mode="LIVE" />);
    expect(container.querySelector(".text-profit")).toBeTruthy();
  });

  it("applies muted styling for PAPER mode", () => {
    const { container } = render(<TradingModeBadge mode="PAPER" />);
    expect(container.querySelector(".text-muted-foreground")).toBeTruthy();
  });
});
