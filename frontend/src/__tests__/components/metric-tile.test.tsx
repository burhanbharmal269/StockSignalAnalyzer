import { render, screen } from "@testing-library/react";
import { MetricTile } from "@/components/shared/metric-tile";
import { DollarSign } from "lucide-react";

describe("MetricTile", () => {
  it("renders label and value", () => {
    render(<MetricTile label="Capital" value="₹1,00,000" />);
    expect(screen.getByText("Capital")).toBeTruthy();
    expect(screen.getByText("₹1,00,000")).toBeTruthy();
  });

  it("renders sub text when provided", () => {
    render(<MetricTile label="Capital" value="₹1,00,000" sub="Mode: HYBRID" />);
    expect(screen.getByText("Mode: HYBRID")).toBeTruthy();
  });

  it("renders icon when provided", () => {
    const { container } = render(
      <MetricTile label="Capital" value="₹1,00,000" icon={DollarSign} />
    );
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("applies profit color for up trend", () => {
    const { container } = render(
      <MetricTile label="PnL" value="+₹500" trend="up" />
    );
    expect(container.querySelector(".text-profit")).toBeTruthy();
  });

  it("applies loss color for down trend", () => {
    const { container } = render(
      <MetricTile label="PnL" value="-₹500" trend="down" />
    );
    expect(container.querySelector(".text-loss")).toBeTruthy();
  });
});
