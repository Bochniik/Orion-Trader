import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import OpportunityCard from "./OpportunityCard";
import { TodayResults } from "./TodayView";
import AnalyzeView from "./AnalyzeView";
import WorkspaceNav from "../components/WorkspaceNav";
import { currentDecision, price } from "./decisionPresentation";
import { analyzeCoreStock, scanToday, getCoreStatus, setCsrfToken } from "../api/api";

const now = Date.now();
const fixture = {
  ticker: "AAPL", company_name: "Apple Inc.", direction: "LONG", decision: "BUY",
  actionable: true, status: "qualified", confidence: 80, directional_confidence: 80, timestamp: new Date(now - 10000).toISOString(),
  expires_at: new Date(now + 300000).toISOString(), timeframe: "5m",
  entry_zone: [99, 100], invalidation: 98, targets: [104, 105], risk_reward: 2,
  expected_move: 0.4, liquidity_tier: "A", liquidity_score: 90,
  reasons: ["Momentum and model agree."], warnings: [],
  model_outputs: { quote_as_of: new Date(now - 10000).toISOString() },
};
afterEach(() => vi.unstubAllGlobals());

describe("simplified core experience", () => {
  it("renders the four primary workflows and no lab/order controls", () => {
    const html = renderToStaticMarkup(<WorkspaceNav activeView="today" onNavigate={() => {}} />);
    expect(html).toContain("Primary navigation");
    expect(html).toContain('aria-current="page"');
    expect(html).toContain("Dashboard");
    expect(html).toContain("Analysis");
    expect(html).toContain("Orion Intelligence");
    expect(html).toContain("Watchlist");
    for (const forbidden of ["Build / validate", "Paper agent", "Submit order", "Latest signal", "Buying power", "Live Edge", "Orion AI"]) expect(html).not.toContain(forbidden);
  });
  it("puts the verdict and plan before expandable evidence", () => {
    const html = renderToStaticMarkup(<OpportunityCard decision={fixture} now={now} />);
    expect(html).toContain("Apple Inc.");
    expect(html).toContain("LONG");
    expect(html).toContain("80%");
    expect(html.indexOf("Entry zone")).toBeLessThan(html.indexOf("<summary>Details"));
    expect(html).toContain("1 : 2");
    expect(html).not.toContain("<details open");
  });
  it("withholds price levels and confidence for WAIT", () => {
    const decision = { ...fixture, actionable: false, confidence: null, directional_confidence: null, direction: "WAIT", decision: "WAIT" };
    const html = renderToStaticMarkup(<OpportunityCard decision={decision} />);
    expect(html).toContain("Unavailable");
    expect(html).toContain("No trade plan issued");
    expect(html).not.toContain("<dt>Entry zone");
    expect(html).not.toContain("80%");
  });
  it("degrades an expired card to WAIT without mutating the evidence", () => {
    const original = structuredClone(fixture);
    const expired = currentDecision(fixture, now + 120000);
    expect(expired.direction).toBe("WAIT");
    expect(expired.confidence).toBeNull();
    expect(expired.entry_zone).toBeNull();
    expect(fixture).toEqual(original);
    expect(currentDecision({ ...fixture, model_outputs: {} }, now).actionable).toBe(false);
  });
  it("does not convert absent prices to zero dollars", () => {
    expect(price(null)).toBe("Unavailable");
    expect(price(undefined)).toBe("Unavailable");
  });
  it("distinguishes no qualifying setups from unavailable or partial scans", () => {
    const empty = renderToStaticMarkup(<TodayResults result={{ status: "ready", opportunities: [] }} />);
    expect(empty).toContain("No high-quality setups detected right now.");
    const missing = renderToStaticMarkup(<TodayResults result={{ status: "unavailable", opportunities: [], message: "Data not connected" }} />);
    expect(missing).toContain("Market scan unavailable");
    expect(missing).not.toContain("No high-quality setups detected right now.");
    const partial = renderToStaticMarkup(<TodayResults result={{ status: "partial", opportunities: [] }} />);
    expect(partial).toContain("Scan incomplete");
  });
  it("caps the visible board at five cards", () => {
    const opportunities = Array.from({ length: 8 }, (_, i) => ({ ...fixture, ticker: `TEST${i}` }));
    const html = renderToStaticMarkup(<TodayResults result={{ status: "ready", opportunities }} />);
    expect(html.match(/aria-label="TEST\d analysis"/g)).toHaveLength(5);
  });
  it("has one Analyze input and no manual statistical controls", () => {
    const html = renderToStaticMarkup(<AnalyzeView />);
    expect(html).toContain('id="analyze-ticker"');
    expect(html).toContain("Missing evidence means WAIT, not an invented answer.");
    expect(html).not.toContain("Build baseline");
    expect(html).not.toContain("Choose models");
  });
  it("uses authenticated core endpoints, encoded tickers and cancellation signals", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, headers: { get: () => "application/json" }, json: async () => ({}) }));
    const controller = new AbortController();
    setCsrfToken("test-csrf");
    await analyzeCoreStock(" brk.b ", { signal: controller.signal });
    expect(fetch).toHaveBeenLastCalledWith("http://127.0.0.1:8000/core/analyze/BRK.B", expect.objectContaining({ method: "POST", credentials: "include", signal: controller.signal, headers: { "X-CSRF-Token": "test-csrf" } }));
    await scanToday();
    expect(fetch.mock.lastCall[0]).toContain("/core/today");
    await getCoreStatus();
    expect(fetch.mock.lastCall[0]).toContain("/core/status");
    setCsrfToken("");
  });
});
