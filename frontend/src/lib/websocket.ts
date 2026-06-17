import { WS_BASE_URL, WS_RECONNECT_DELAY, WS_MAX_RECONNECT_ATTEMPTS, TOKEN_KEY } from "./constants";
import { getAccessToken } from "./auth";
import type { WSEventType, WSMessage } from "@/types";

type EventHandler<T = unknown> = (msg: WSMessage<T>) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private handlers = new Map<WSEventType, Set<EventHandler>>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = true;

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

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

    this.ws.onclose = () => {
      if (!this.shouldReconnect) return;
      if (this.reconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
        this.reconnectAttempts++;
        this.reconnectTimer = setTimeout(() => this.connect(), WS_RECONNECT_DELAY);
      }
    };

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
    };
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
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
