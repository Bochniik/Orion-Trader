import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startMarketStatePolling, SCANNER_POLL_MS } from "./marketStatePolling";

describe("Read-only market-state polling", () => {
  let stop;
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { stop?.(); vi.clearAllTimers(); vi.useRealTimers(); });
  const readers = () => ({ scanner: vi.fn().mockResolvedValue({ status: "ready" }), intelligence: vi.fn().mockResolvedValue({ categories: {} }) });
  it("reads both streams immediately then every 15s without selecting or starting scans", async () => {
    const sources = readers(), update = vi.fn();
    stop = startMarketStatePolling(update, { readers: sources, visible: () => true });
    await vi.advanceTimersByTimeAsync(0);
    expect(sources.scanner).toHaveBeenCalledTimes(1);
    expect(sources.intelligence).toHaveBeenCalledTimes(1);
    expect(Object.keys(sources.intelligence.mock.calls[0][0])).toEqual(["signal"]);
    await vi.advanceTimersByTimeAsync(SCANNER_POLL_MS);
    expect(sources.intelligence).toHaveBeenCalledTimes(2);
    expect(update).toHaveBeenCalledTimes(4);
  });
  it("isolates an endpoint failure and recovers on the next read", async () => {
    const sources = readers(), update = vi.fn();
    sources.intelligence.mockRejectedValueOnce(new Error("offline"));
    stop = startMarketStatePolling(update, { readers: sources, visible: () => true });
    await vi.advanceTimersByTimeAsync(0);
    expect(update).toHaveBeenCalledWith("scanner", { value: { status: "ready" }, error: "" });
    expect(update).toHaveBeenCalledWith("intelligence", { error: "offline" });
    await vi.advanceTimersByTimeAsync(SCANNER_POLL_MS);
    expect(update).toHaveBeenCalledWith("intelligence", { value: { categories: {} }, error: "" });
  });
  it("pauses hidden-page reads and cancels cleanly without post-unmount updates", async () => {
    const sources = readers(), update = vi.fn();
    let resolve;
    sources.intelligence.mockImplementation(() => new Promise(done => { resolve = done; }));
    stop = startMarketStatePolling(update, { readers: sources, visible: () => false });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(14000);
    stop();
    expect(sources.intelligence.mock.calls[0][0].signal.aborted).toBe(true);
    resolve({ categories: {} });
    await vi.advanceTimersByTimeAsync(30000);
    expect(sources.intelligence).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledTimes(1);
  });
  it("rejects malformed intelligence instead of silently clearing errors", async () => {
    const sources = readers(), update = vi.fn();
    sources.intelligence.mockResolvedValue({});
    stop = startMarketStatePolling(update, { readers: sources });
    await vi.advanceTimersByTimeAsync(0);
    expect(update).toHaveBeenCalledWith("intelligence", { error: "Invalid market-state response." });
  });
  it("bounds hung GET requests and prevents overlapping reads", async () => {
    const sources = readers(), update = vi.fn();
    sources.intelligence.mockImplementation(({ signal }) => new Promise((_, reject) => signal.addEventListener("abort", () => reject(Object.assign(new Error(), { name: "AbortError" })))));
    stop = startMarketStatePolling(update, { readers: sources, visible: () => true });
    await vi.advanceTimersByTimeAsync(15000);
    expect(update).toHaveBeenCalledWith("intelligence", { error: "Market-state read timed out." });
    expect(sources.intelligence.mock.calls[0][0].signal.aborted).toBe(true);
    expect(sources.intelligence.mock.calls.length).toBeLessThanOrEqual(2);
  });
});
