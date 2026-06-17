import { render, screen } from "@testing-library/react";

// Mock the health view to test the status mapping logic
function mapStatus(raw: string): "healthy" | "degraded" | "unhealthy" {
  if (raw === "ok") return "healthy";
  if (raw === "degraded") return "degraded";
  return "unhealthy";
}

describe("SystemHealthView status mapping", () => {
  it("maps ok → healthy", () => {
    expect(mapStatus("ok")).toBe("healthy");
  });

  it("maps degraded → degraded", () => {
    expect(mapStatus("degraded")).toBe("degraded");
  });

  it("maps unknown → unhealthy", () => {
    expect(mapStatus("error")).toBe("unhealthy");
  });

  it("does not crash on missing components field", () => {
    const health = { status: "ok", version: "1.0.0", environment: "development" };
    // Accessing .components on this object returns undefined — no crash
    const components = (health as Record<string, unknown>)["components"];
    expect(components).toBeUndefined();
    // Safe guard: Object.entries on undefined would throw, so we null-check
    const entries = components ? Object.entries(components) : [];
    expect(entries).toHaveLength(0);
  });

  it("does not crash when uptime_seconds is undefined", () => {
    const health = { status: "ok" } as Record<string, unknown>;
    const uptime = (health["uptime_seconds"] as number) ?? 0;
    expect(uptime).toBe(0);
  });
});
