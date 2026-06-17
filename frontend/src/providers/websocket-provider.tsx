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
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) return;

    wsManager.connect();
    const interval = setInterval(() => {
      setIsConnected(wsManager.isConnected);
      // Reconnect if disconnected (token may have been refreshed)
      if (!wsManager.isConnected) wsManager.connect();
    }, 5_000);

    return () => {
      clearInterval(interval);
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
