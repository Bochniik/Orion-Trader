import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ScannerCandidateCard from "./ScannerCandidateCard";
import { ScannerStateView, SCANNER_POLL_MS, scannerProgress, scannerStatusLabel } from "./TodayView";

const candidate = {
  ticker: "NVDA", company_name: "NVIDIA Corporation", current_price: 142.25,
  model_direction: "UP", directional_confidence: 76, opportunity_score: 88,
  liquidity_score: 94, relative_volume: 2.4, expected_horizon: "15m",
  setup_tags: ["momentum_candidate", "unusual_activity"],
  reasons: ["Strong momentum and high liquidity."], final_decision: "NO_TRADE",
  actionable: false, scanner_freshness: { state: "current", feature_age_seconds: 32 },
};

describe("Today scanner surface", () => {
  it.each([["starting", "SCANNING"], ["market_closed", "MARKET CLOSED"], ["inactive", "SCANNER INACTIVE"]])("distinguishes %s from missing market data", (status, label) => {
    const html = renderToStaticMarkup(<ScannerStateView state={{ status, message: "Provider is configured; runtime diagnostic.", universe: {} }} />);
    expect(html).toContain(label);
    expect(html).toContain("Provider is configured; runtime diagnostic.");
    expect(html).not.toContain("MARKET DATA UNAVAILABLE");
    expect(html).not.toContain("Scanner is waiting for a connected market-data source.");
  });

  it("renders exact backend configuration diagnostics without masking missing credentials", () => {
    const message = "Alpaca research credentials are not connected for this user. Reconnect after a backend restart.";
    const html = renderToStaticMarkup(<ScannerStateView state={{ status: "unavailable", message, universe: {} }} onOpenData={() => {}} />);
    expect(html).toContain(message);
    expect(html).toContain("Set up research data");
    expect(html).toContain("Universe scanned: Unavailable");
  });

  it("shows an intentional first-scan loading state without inventing progress", () => {
    const html = renderToStaticMarkup(<ScannerStateView />);
    expect(html).toContain("Orion is scanning the market");
    expect(html).toContain("Results will appear here without a reload.");
    expect(html).not.toContain("Universe scanned:");
  });

  it("renders scanner candidates with decision fields and no probability label for score", () => {
    const html = renderToStaticMarkup(<ScannerStateView state={{ status: "ready", freshness: { state: "current", snapshot_age_seconds: 32 }, scanner_running: true,
      top_candidates: [candidate], universe: { total_symbols: 4300, next_offset: 750, current_page: 3, pages_total: 18 }, active_candidate_count: 18 }} />);
    expect(html).toContain("ORION MARKET SCANNER");
    expect(html).toContain("NVDA");
    expect(html).toContain("Directional confidence");
    expect(html).toContain("76.0%");
    expect(html).toContain("Opportunity Score");
    expect(html).toContain("88.0 / 100");
    expect(html).not.toContain("88% probability");
    expect(html).toContain("Liquidity");
    expect(html).toContain("94.0 / 100");
    expect(html).toContain("RVOL 2.40×");
    expect(html).toContain("Horizon 15m");
    expect(html).toContain("NO TRADE");
    expect(html).toContain("Interesting opportunity ≠ approved trade setup.");
    expect(html).toContain("Universe scanned: 750 / 4,300");
    expect(html).toContain("Current page: 3 / 18");
  });

  it("shows current, delayed and stale freshness without relabeling delayed data", () => {
    expect(scannerStatusLabel({ status: "ready", freshness: { state: "current" } })).toBe("CURRENT");
    expect(scannerStatusLabel({ status: "ready", freshness: { state: "delayed" } })).toBe("DELAYED DATA");
    expect(scannerStatusLabel({ status: "stale", freshness: { state: "stale" } })).toBe("STALE");
    const delayed = renderToStaticMarkup(<ScannerCandidateCard candidate={{ ...candidate, scanner_freshness: { state: "delayed", feature_age_seconds: 480 } }} />);
    expect(delayed).toContain("DELAYED DATA");
    expect(delayed).not.toContain("CURRENT");
    const stale = renderToStaticMarkup(<ScannerStateView state={{ status: "stale", freshness: { state: "stale", snapshot_age_seconds: 1020 }, last_known_candidates: [candidate], universe: {} }} />);
    expect(stale).toContain("STALE");
    expect(stale).toContain("Last known candidates");
  });

  it("renders unavailable and no-opportunity states instead of a blank panel", () => {
    const unavailable = renderToStaticMarkup(<ScannerStateView state={{ status: "unavailable", freshness: { state: "unavailable" }, universe: {} }} onOpenData={() => {}} />);
    expect(unavailable).toContain("MARKET DATA UNAVAILABLE");
    expect(unavailable).toContain("Set up research data");
    const empty = renderToStaticMarkup(<ScannerStateView state={{ status: "no_high_quality_candidates", freshness: { state: "current" }, top_candidates: [], universe: {} }} />);
    expect(empty).toContain("No high-quality opportunities detected.");
    expect(empty).toContain("Orion will continue scanning automatically.");
  });

  it("does not invent progress when the universe total is unknown and polls cheaply", () => {
    expect(scannerProgress({ universe: { next_offset: 10 } })).toBeNull();
    expect(SCANNER_POLL_MS).toBe(15000);
    const html = renderToStaticMarkup(<ScannerStateView state={{ status: "ready", freshness: { state: "current" }, top_candidates: [], universe: { next_offset: 10 } }} />);
    expect(html).toContain("Universe scanned: Unavailable");
  });
});
