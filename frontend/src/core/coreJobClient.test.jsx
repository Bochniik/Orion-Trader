import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect, vi, afterEach } from "vitest";
import { runCoreJob } from "./coreJobClient";
import { PlanRows } from "./SavedPlans";
import { currentDecision } from "./decisionPresentation";
import { startCoreJob, getCoreJob, cancelCoreJob, saveCorePlan, stopCorePlan, setCsrfToken } from "../api/api";

afterEach(() => vi.unstubAllGlobals());
function fake(overrides = {}) {
  return { start: vi.fn(async () => ({ id: "job", state: "running", stage: "Validating" })),
           get: vi.fn(async () => ({ id: "job", state: "completed", stage: "Done", result: { decision: "WAIT" } })),
           cancel: vi.fn(async () => ({})), wait: vi.fn(async () => {}), ...overrides };
}

describe("one-action research job client", () => {
  it("waits for final results and reports real stage labels", async () => {
    const api = fake(), onProgress = vi.fn();
    const result = await runCoreJob({ kind: "analyze", ticker: "AAPL" }, { onProgress }, api);
    expect(result).toMatchObject({ decision: "WAIT", direction: "WAIT", bias: "WAIT", model_direction: null, strategy_bias: null });
    expect(result.reasons).toEqual([]);
    expect(result.warnings).toEqual([]);
    expect(result).not.toHaveProperty("confidence");
    expect(result).not.toHaveProperty("directional_confidence");
    expect(onProgress).toHaveBeenCalledWith("Validating");
    expect(api.start).toHaveBeenCalledOnce();
    expect(api.cancel).not.toHaveBeenCalled();
  });
  it("cancels an acknowledged server job when navigation aborts", async () => {
    const controller = new AbortController();
    const api = fake({ wait: vi.fn(async () => controller.abort()) });
    await expect(runCoreJob({ kind: "today" }, { signal: controller.signal }, api)).rejects.toThrow("cancelled");
    expect(api.cancel).toHaveBeenCalledWith("job");
  });
  it("does not lose a job whose start response arrives after cancellation", async () => {
    const controller = new AbortController();
    const api = fake({ start: vi.fn(async () => { controller.abort(); return { id: "late-job", state: "running" }; }) });
    await expect(runCoreJob({ kind: "today" }, { signal: controller.signal }, api)).rejects.toThrow("cancelled");
    expect(api.cancel).toHaveBeenCalledWith("late-job");
    expect(api.get).not.toHaveBeenCalled();
  });
  it("does not force a result after timeout or backend interruption", async () => {
    const api = fake({ get: vi.fn(async () => ({ id: "job", state: "interrupted", stage: "Backend stopped" })) });
    await expect(runCoreJob({ kind: "today" }, {}, api)).rejects.toThrow("Backend stopped");
  });
  it("requests cancellation if status polling fails", async () => {
    const api = fake({ get: vi.fn(async () => { throw new Error("Network unavailable"); }) });
    await expect(runCoreJob({ kind: "today" }, {}, api)).rejects.toThrow("Network unavailable");
    expect(api.cancel).toHaveBeenCalledWith("job");
  });
  it("waits on bounded admission but does not retry authentication failures", async () => {
    const start = vi.fn().mockRejectedValueOnce(Object.assign(new Error("Busy"), { status: 409 }))
      .mockResolvedValue({ id: "job", state: "completed", result: {} });
    const api = fake({ start });
    await runCoreJob({ kind: "today" }, {}, api);
    expect(start).toHaveBeenCalledTimes(2);
    const denied = fake({ start: vi.fn(async () => { throw Object.assign(new Error("Unauthorized"), { status: 401 }); }) });
    await expect(runCoreJob({ kind: "today" }, {}, denied)).rejects.toThrow("Unauthorized");
    expect(denied.start).toHaveBeenCalledOnce();
  });
  it("bounds busy retries", async () => {
    const api = fake({ start: vi.fn(async () => { throw Object.assign(new Error("Busy"), { status: 409 }); }) });
    await expect(runCoreJob({ kind: "today" }, {}, api)).rejects.toThrow("Busy");
    expect(api.start).toHaveBeenCalledTimes(30);
  });
  it("shows saved plan evidence as observations, not achieved trades", () => {
    const html = renderToStaticMarkup(<PlanRows plans={[{ decision_id: "id", decision: { ticker: "AAPL", direction: "LONG", timeframe: "5m" },
      latest_check: { message: "Target and invalidation touched; order unknown.", outcome: { reference_return_percent: 1 } } }]} />);
    expect(html).toContain("order unknown");
    expect(html).toContain("not an executed trade");
    expect(html).toContain("Stop monitoring");
  });
  it("protects all job and plan writes with the existing CSRF/session contract", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, headers: { get: () => "application/json" }, json: async () => ({}) }));
    setCsrfToken("safe-token");
    await startCoreJob({ kind: "analyze", ticker: "AAPL" });
    expect(fetch.mock.lastCall[1]).toMatchObject({ method: "POST", credentials: "include", headers: { "X-CSRF-Token": "safe-token" } });
    await getCoreJob("job/id");
    expect(fetch.mock.lastCall[0]).toContain("job%2Fid");
    await cancelCoreJob("id");
    expect(fetch.mock.lastCall[1].method).toBe("DELETE");
    await saveCorePlan("id");
    expect(fetch.mock.lastCall[0]).toContain("/core/plans/id");
    await stopCorePlan("id");
    expect(fetch.mock.lastCall[1]).toMatchObject({ method: "DELETE", headers: { "X-CSRF-Token": "safe-token" } });
  });
  it("expires required benchmark evidence even if stock and quote remain fresh", () => {
    const now = Date.now(), fresh = new Date(now - 10000).toISOString();
    const row = { actionable: true, timeframe: "5m", timestamp: fresh, expires_at: new Date(now + 60000).toISOString(),
      model_outputs: { core_validation: { ready: true }, quote_as_of: fresh, feature_snapshot: { timestamp: fresh,
        feature_provenance: Object.fromEntries(["price_momentum", "atr_14", "realized_volatility", "relative_volume", "index_momentum", "relative_strength_market"].map(name => [name, { status: "fresh", as_of: fresh }])) } } };
    expect(currentDecision(row, now).actionable).toBe(true);
    row.model_outputs.feature_snapshot.feature_provenance.index_momentum.as_of = new Date(now - 121000).toISOString();
    expect(currentDecision(row, now).actionable).toBe(false);
  });
});
