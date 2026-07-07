/**
 * Indian equity market hours (NSE/BSE) utilities.
 *
 * Regular session: 09:15 – 15:30 IST, Mon–Fri
 * Pre-market:      09:00 – 09:15 IST (read-only, limited data)
 *
 * Holiday list is intentionally not maintained here — the backend scanner
 * already gates trading on holidays. For the frontend, the day-of-week +
 * time-of-day check is sufficient to avoid polling during obviously closed
 * periods (nights, weekends).
 */

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000; // UTC+5:30

/**
 * Return a Date whose UTC getters (getUTCHours, getUTCMinutes, getUTCDay)
 * read as if the clock were in IST. Date.now() is always UTC so we simply
 * add the fixed IST offset — no local-timezone math needed.
 */
function nowIST(): Date {
  return new Date(Date.now() + IST_OFFSET_MS);
}

/**
 * Returns true during the NSE/BSE regular trading session:
 * Monday–Friday, 09:15–15:30 IST.
 */
export function isMarketOpen(): boolean {
  const ist = nowIST();
  const day = ist.getUTCDay(); // 0=Sun, 6=Sat in UTC (shifted by IST means same day for most of the day)
  if (day === 0 || day === 6) return false; // weekend

  const hhmm = ist.getUTCHours() * 100 + ist.getUTCMinutes();
  return hhmm >= 915 && hhmm < 1530;
}

/**
 * Returns true during pre-market OR regular session (09:00–15:30 IST).
 * Use for data that's valid in pre-market too.
 */
export function isMarketOrPreOpen(): boolean {
  const ist = nowIST();
  const day = ist.getUTCDay();
  if (day === 0 || day === 6) return false;

  const hhmm = ist.getUTCHours() * 100 + ist.getUTCMinutes();
  return hhmm >= 900 && hhmm < 1530;
}

/** Human-readable session label for the current time. */
export function marketSessionLabel(): "pre-open" | "open" | "closed" {
  const ist = nowIST();
  const day = ist.getUTCDay();
  if (day === 0 || day === 6) return "closed";

  const hhmm = ist.getUTCHours() * 100 + ist.getUTCMinutes();
  if (hhmm >= 900 && hhmm < 915) return "pre-open";
  if (hhmm >= 915 && hhmm < 1530) return "open";
  return "closed";
}
