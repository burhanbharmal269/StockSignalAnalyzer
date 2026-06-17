"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { wsManager } from "@/lib/websocket";
import { useAuth } from "./auth-provider";

interface WSContextValue {
  isConnected: boolean;
}

const WSContext = createContext<WSContextValue>({ isConnected: false });

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  // Lazy init so top-nav never flickers "Offline" if WS is already open
  const [isConnected, setIsConnected] = useState(() => wsManager.isConnected);

  useEffect(() => {
    if (!isAuthenticated) return;

    wsManager.connect();
    // Sync immediately after attempting connect (may already be OPEN)
    setIsConnected(wsManager.isConnected);

    // Event-driven: update state the moment WS opens or closes
    const unsub = wsManager.onStatusChange(setIsConnected);

    // Fallback heartbeat: forceReconnect with fresh token every 30s if down
    const interval = setInterval(() => {
      if (!wsManager.isConnected) wsManager.forceReconnect();
    }, 30_000);

    return () => {
      clearInterval(interval);
      unsub();
      wsManager.disconnect();
    };
  }, [isAuthenticated]);

  return (
    <WSContext.Provider value={{ isConnected }}>{children}</WSContext.Provider>
  );
}

export function useWSStatus() {
  return useContext(WSContext);
}
