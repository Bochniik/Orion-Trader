import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import MarketIntelligenceView, { MARKET_CATEGORIES, MarketCategorySelector, MarketIntelligenceCard, observationFreshness, categoryMetric } from "./MarketIntelligenceView";
import { ScannerStateView } from "./TodayView";

const now = Date.parse("2026-09-02T15:30:00Z");
const row = { ticker: "NVDA", current_price: 140.5, ranking_value: 2.5, change_percent: 3.25, liquidity_score: 94,
  data_timestamp: "2026-09-02T15:29:40Z", provider: "alpaca", feed: "iex", reason: "Observed market evidence.",
  freshness: { state: "current", evidence_timestamp: "2026-09-02T15:29:40Z", maximum_price_age_seconds: 120, maximum_evidence_age_seconds: 120 } };
const data = { coverage: { retained_qualified_symbols: 40, universe: { total_symbols: 4300, next_offset: 250 } },
  categories: Object.fromEntries(MARKET_CATEGORIES.slice(1).map(([key]) => [key, { items: [{ ...row, ticker: key === "biggest_losers" ? "LOSS" : "NVDA" }], last_known: [] }])) };
const html = (category, overrides = {}) => renderToStaticMarkup(<MarketIntelligenceView data={data} category={category} now={now} onAnalyze={() => {}} {...overrides} />);

describe("TODAY market intelligence", () => {
  it("opens the completed-session brief visibly without promoting stale rows to live", () => {
    const historical = { ...data, display_mode: "historical", session_date: "2026-09-01",
      limitations: "Daily closes only.", categories: { most_active: { items: [], last_known: [
        { ...row, historical: true, session_date: "2026-09-01", ranking_value: 250000000, provider: "yahoo" },
      ] } } };
    const output = html("most_active", { data: historical });
    expect(output).toContain('open=""');
    expect(output).toContain("2026-09-01 · HISTORICAL / STALE");
    expect(output).toContain("Adjusted session close");
    expect(output).toContain("$250M activity proxy");
    expect(output).toContain("Partial liquidity");
    expect(output).toContain("Analyze NVDA");
    expect(output).not.toContain("No fresh qualifying observations");
    expect(output).not.toContain("CURRENT");
    expect(output).not.toContain("$250M traded");
  });
  it("explains unsupported historical technical categories without inventing evidence", () => {
    const output = html("buy_pressure", { data: { display_mode: "historical", categories: { buy_pressure: { items: [], last_known: [] } } } });
    expect(output).toContain("Inferred Quote Pressure");
    expect(output).toContain("Daily closes cannot supply intraday setups or quote pressure");
    expect(output).not.toContain("NVDA");
  });
  it("offers all nine controlled, keyboard-accessible category buttons", () => {
    const select = vi.fn();
    const selector = MarketCategorySelector({ selected: "orion_picks", onSelect: select });
    const buttons = selector.props.children;
    expect(buttons).toHaveLength(9);
    expect(buttons[0].props["aria-pressed"]).toBe(true);
    buttons[2].props.onClick();
    expect(select).toHaveBeenCalledWith("biggest_losers");
    expect(html("biggest_gainers")).toContain("NVDA");
    expect(html("biggest_losers")).toContain("LOSS");
    expect(html("biggest_losers")).not.toContain("NVDA");
  });
  it("renders useful compact fields and partial rotation coverage", () => {
    const output = html("unusual_volume");
    for (const value of ["$140.50", "2.50× relative volume", "+3.25%", "94 / 100", "CURRENT", "PARTIAL MARKET COVERAGE", "250 / 4300", "Observed market evidence."]) expect(output).toContain(value);
    expect(output).not.toContain("<table");
    expect(output).not.toContain("probability");
  });
  it.each(["buy_pressure", "sell_pressure"])("labels %s as inferred quote sizes, not executed flow", category => {
    expect(html(category)).toContain("Inferred Quote Pressure");
    expect(html(category)).toContain("not executed buying or selling");
    expect(html(category)).toContain("quote imbalance");
  });
  it("preserves activity and mean-reversion meanings", () => {
    expect(html("most_active")).toContain("not “Most Bought”");
    expect(html("potential_bargains")).toContain("2.50 ATR below VWAP");
    expect(html("potential_bargains")).toContain("Missing statistical evidence excludes a stock");
    expect(categoryMetric("most_active", 250000000)).toBe("$250M traded");
    expect(categoryMetric("biggest_losers", -3)).toBe("-3.00% session move");
    expect(categoryMetric("unusual_volume", null)).toBe("Unavailable");
  });
  it("passes the clicked ticker into the existing Analyze callback", () => {
    const onAnalyze = vi.fn();
    const card = MarketIntelligenceCard({ row, category: "most_active", now, onAnalyze });
    card.props.children[0].props.children[0].props.onClick();
    expect(onAnalyze).toHaveBeenCalledExactlyOnceWith("NVDA");
  });
  it("keeps delayed evidence delayed and ages canonical timestamps locally", () => {
    const delayed = { ...row, freshness: { ...row.freshness, state: "delayed" } };
    expect(observationFreshness(delayed, now)).toBe("delayed");
    expect(observationFreshness(row, now + 101000)).toBe("stale");
    expect(observationFreshness({ ...row, data_timestamp: null }, now)).toBe("unavailable");
    const output = html("most_active", { data: { ...data, categories: { most_active: { items: [delayed] } } } });
    expect(output).toContain("DELAYED");
    expect(output).not.toContain("CURRENT");
  });
  it("demotes cached data on read failures and separates last-known stale rows", () => {
    const output = html("most_active", { error: "Disconnected" });
    expect(output).toContain("STALE");
    expect(output).toContain("No fresh qualifying observations");
    expect(output).toContain("Last known observations");
    expect(output).not.toContain("CURRENT");
    expect(html("most_active", { now: now + 121000 })).not.toContain("CURRENT");
  });
  it("does not call empty or unavailable evidence current", () => {
    expect(html("most_active", { data: null })).toContain("Loading market intelligence");
    const empty = html("most_active", { data: { categories: {} } });
    expect(empty).toContain("UNAVAILABLE");
    expect(empty).toContain("No fresh qualifying observations");
  });
  it("displays the provider/session diagnostic on intelligence categories too", () => {
    expect(html("most_active", { data: { ...data, message: "Market is closed; provider remains connected." } })).toContain("Market is closed; provider remains connected.");
  });
  it("also marks cached Orion Picks stale on polling failure", () => {
    const output = renderToStaticMarkup(<ScannerStateView error="Read failed" state={{ status: "ready", freshness: { state: "current" }, top_candidates: [{ ticker: "NVDA", scanner_freshness: { state: "current" } }] }} />);
    expect(output).toContain("STALE");
    expect(output).not.toContain("CURRENT");
  });
});
