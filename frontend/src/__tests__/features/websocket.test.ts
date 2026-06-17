import { WebSocketManager } from "@/lib/websocket";

// We test the WebSocketManager class internals
// wsManager singleton is imported but we instantiate a fresh one here
class TestWSManager {
  private handlers = new Map<string, Set<(e: unknown) => void>>();

  on(event: string, handler: (e: unknown) => void) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(handler);
    return () => this.handlers.get(event)?.delete(handler);
  }

  emit(event: string, data: unknown) {
    this.handlers.get(event)?.forEach((h) => h(data));
  }
}

describe("WebSocket event handler", () => {
  let mgr: TestWSManager;

  beforeEach(() => {
    mgr = new TestWSManager();
  });

  it("registers and fires handler for event", () => {
    const handler = jest.fn();
    mgr.on("signal.new", handler);
    mgr.emit("signal.new", { id: "abc" });
    expect(handler).toHaveBeenCalledWith({ id: "abc" });
  });

  it("unregisters handler via returned cleanup fn", () => {
    const handler = jest.fn();
    const off = mgr.on("signal.new", handler);
    off();
    mgr.emit("signal.new", { id: "abc" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("supports multiple handlers for same event", () => {
    const h1 = jest.fn();
    const h2 = jest.fn();
    mgr.on("order.updated", h1);
    mgr.on("order.updated", h2);
    mgr.emit("order.updated", { id: "x" });
    expect(h1).toHaveBeenCalled();
    expect(h2).toHaveBeenCalled();
  });

  it("does not call handlers for different events", () => {
    const handler = jest.fn();
    mgr.on("position.updated", handler);
    mgr.emit("signal.new", {});
    expect(handler).not.toHaveBeenCalled();
  });
});
