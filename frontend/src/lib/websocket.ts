import { WS_BASE_URL, WS_RECONNECT_DELAY, TOKEN_KEY } from "./constants";
import { getAccessToken } from "./auth";
import type { WSEventType, WSMessage } from "@/types";

type EventHandler<T = unknown> = (msg: WSMessage<T>) => void;
type StatusHandler = (connected: boolean) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private handlers = new Map<WSEventType, Set<EventHandler>>();
  private statusHandlers = new Set<StatusHandler>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return;

    const token = typeof window !== "undefined" ? getAccessToken() : null;
    if (!token) return;

    const url = `${WS_BASE_URL}/ws?token=${encodeURIComponent(token)}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        if (!msg.type) return;
        const handlers = this.handlers.get(msg.type);
        handlers?.forEach((h) => h(msg));
      } catch {
        // malformed frame — skip
      }
    };

    this.ws.onopen = () => {
      this._notifyStatus(true);
    };

    this.ws.onclose = () => {
      this._notifyStatus(false);
      if (this.stopped) return;
      this.reconnectTimer = setTimeout(() => this.connect(), WS_RECONNECT_DELAY);
    };
  }

  /** Hard reset — clears stop flag, drops existing socket, reconnects with fresh token. */
  forceReconnect() {
    this.stopped = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.connect();
  }

  disconnect() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this._notifyStatus(false);
  }

  onStatusChange(handler: StatusHandler) {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  private _notifyStatus(connected: boolean) {
    this.statusHandlers.forEach((h) => h(connected));
  }

  on<T>(event: WSEventType, handler: EventHandler<T>) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler as EventHandler);
    return () => this.off(event, handler);
  }

  off<T>(event: WSEventType, handler: EventHandler<T>) {
    this.handlers.get(event)?.delete(handler as EventHandler);
  }

  get isConnected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export { WebSocketManager };
export const wsManager = new WebSocketManager();
