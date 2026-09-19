import { getCoreSession, getCurrentScannerState, getMarketIntelligence } from "../api/api";

export const SCANNER_POLL_MS = 15000;

// Only read cached backend state. Selection changes never initiate scan jobs.
export function startMarketStatePolling(onUpdate, {
  readers = { session: getCoreSession, scanner: getCurrentScannerState, intelligence: getMarketIntelligence },
  timers = globalThis, visible = () => document.visibilityState === "visible",
} = {}) {
  let stopped = false;
  const pending = new Map();
  const read = () => {
    if (stopped) return;
    for (const [key, reader] of Object.entries(readers)) {
      if (pending.has(key)) continue;
      const controller = new AbortController();
      pending.set(key, controller);
      // Bound a hung read without overlapping requests or touching the scanner.
      const timeout = timers.setTimeout(() => controller.abort(), SCANNER_POLL_MS);
      Promise.resolve().then(() => reader({ signal: controller.signal })).then(value => {
        if (!value || typeof value !== "object" || (key === "intelligence" && !value.categories) || (key === "session" && !value.mode)) {
          throw new Error("Invalid market-state response.");
        }
        if (!stopped) onUpdate(key, { value, error: "" });
      }).catch(error => {
        if (!stopped) onUpdate(key, { error: error?.name === "AbortError" ? "Market-state read timed out." : error?.message || "Market state unavailable." });
      }).finally(() => { timers.clearTimeout(timeout); pending.delete(key); });
    }
  };
  read();
  const timer = timers.setInterval(() => { if (visible()) read(); }, SCANNER_POLL_MS);
  return () => { stopped = true; timers.clearInterval(timer); for (const controller of pending.values()) controller.abort(); };
}
