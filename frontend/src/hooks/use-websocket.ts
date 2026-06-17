"use client";

import { useEffect } from "react";
import { wsManager } from "@/lib/websocket";
import type { WSEventType, WSEvent } from "@/types";

export function useWebSocket<T>(
  event: WSEventType,
  handler: (data: WSEvent<T>) => void
) {
  useEffect(() => {
    return wsManager.on<T>(event, handler);
  }, [event, handler]);
}
