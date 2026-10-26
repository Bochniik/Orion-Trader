import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import OurAISymbolResearchPanel, { SymbolResearchSummary } from "./OurAISymbolResearchPanel";

const verified = {
  symbol: "NVDA",
  mode: "RESEARCH_SHADOW_ONLY",
  trading_enabled: false,
  decision: null,
  p_up: null,
  p_down: null,
  signed_return_percent: null,
  magnitude_status: "verified_forward",
  magnitude: {
    source: "ourai_verified_forward_journal",
    kind: "absolute_magnitude_only",
    horizon_minutes: 15,
    direction_available: false,
    as_of: "2026-10-26T15:00:00Z",
    resolved: 108,
    pending: 4,
    champion_mae_bps: 12.345,
    latest_expected_magnitude_bps: 8.4,
  },
  news: { status: "unavailable", insights: [] },
};

describe("OurAI per-symbol research", () => {
  it("shows a safe loading state until an authenticated request resolves", () => {
    const html = renderToStaticMarkup(<OurAISymbolResearchPanel selectedTicker="NVDA" />);
    expect(html).toContain("Loading NVDA research evidence");
    expect(html).not.toContain("12.35 bps");
  });

  it("does not fetch or invent evidence for unsupported selections", () => {
    const html = renderToStaticMarkup(<OurAISymbolResearchPanel selectedTicker="RGTI" />);
    expect(html).toContain("Select NVDA, AAPL");
    expect(html).not.toContain("Loading RGTI");
  });

  it("shows only verified magnitude and explicit research-only limits", () => {
    const html = renderToStaticMarkup(<SymbolResearchSummary briefing={verified} selectedTicker="NVDA" />);
    expect(html).toContain("Verified forward journal");
    expect(html).toContain("108");
    expect(html).toContain("12.35 bps");
    expect(html).toContain("8.40 bps");
    expect(html).toContain("2026-10-26 15:00 UTC");
    expect(html).toContain("not independently validated");
    expect(html).not.toContain("LONG");
    expect(html).not.toContain("SHORT");
  });

  it("fails closed on symbol mismatch, missing evidence and altered semantics", () => {
    const variants = [
      { ...verified, symbol: "AAPL" },
      { ...verified, magnitude_status: "unavailable" },
      { ...verified, trading_enabled: true },
      { ...verified, p_up: 0.9 },
      { ...verified, signed_return_percent: 2.5 },
      { ...verified, magnitude: { ...verified.magnitude, direction_available: true } },
      { ...verified, magnitude: { ...verified.magnitude, source: "unverified_file" } },
    ];
    for (const briefing of variants) {
      const html = renderToStaticMarkup(<SymbolResearchSummary briefing={briefing} selectedTicker="NVDA" />);
      expect(html).toContain("Verified NVDA magnitude evidence unavailable");
      expect(html).not.toContain("12.35 bps");
      expect(html).not.toContain("8.40 bps");
    }
  });

  it("does not treat absent metrics as zero or infer news sentiment", () => {
    const html = renderToStaticMarkup(
      <SymbolResearchSummary
        selectedTicker="NVDA"
        briefing={{
          ...verified,
          magnitude: { ...verified.magnitude, champion_mae_bps: null, latest_expected_magnitude_bps: null },
        }}
      />
    );
    expect(html).toContain("Unavailable");
    expect(html).not.toContain("0.00 bps");
    expect(html).toContain("Article-grounded news interpretation is not provided");
  });
});
