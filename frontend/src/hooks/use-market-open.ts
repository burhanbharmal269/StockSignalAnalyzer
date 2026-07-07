"use client";

import { useEffect, useState } from "react";
import { isMarketOpen, marketSessionLabel } from "@/lib/market-hours";

/**
 * Reactively tracks whether the Indian equity market (NSE/BSE) is open.
 * Re-evaluates every minute so UI components respond when the session
 * opens or closes without requiring a page reload.
 *
 * Usage in React Query:
 *   const { marketOpen } = useMarketOpen();
 *   useQuery({ ..., refetchInterval: marketOpen ? 30_000 : false })
 */
export function useMarketOpen() {
  const [marketOpen, setMarketOpen] = useState(isMarketOpen);
  const [session, setSession] = useState(marketSessionLabel);

  useEffect(() => {
    const tick = () => {
      setMarketOpen(isMarketOpen());
      setSession(marketSessionLabel());
    };

    // Align to the next full minute boundary for accurate session-change detection
    const now = Date.now();
    const msToNextMinute = 60_000 - (now % 60_000);
    const initialTimer = setTimeout(() => {
      tick();
      const interval = setInterval(tick, 60_000);
      return () => clearInterval(interval);
    }, msToNextMinute);

    return () => clearTimeout(initialTimer);
  }, []);

  return { marketOpen, session };
}
