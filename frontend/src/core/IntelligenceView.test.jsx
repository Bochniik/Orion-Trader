import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CompactCandidate, PriorityCard } from "./IntelligenceView";

const candidate = {
  ticker: "ASX",
  setup_state: "actionable",
  directional_bias: "bullish",
  setup_quality: 90,
  liquidity_score: 71,
  expected_horizon: "10 sessions",
  confidence: null,
  main_reason: "Strong technical setup with improving momentum and liquidity.",
  main_risk: "Limited historical sample size.",
};

describe("Orion Intelligence cockpit cards", () => {
  it("renders a selected top-priority card without inventing missing confidence", () => {
    const html = renderToStaticMarkup(
      <PriorityCard item={candidate} selected onSelect={() => {}} onAnalyze={() => {}} />
    );

    expect(html).toContain("TOP");
    expect(html).toContain("ASX");
    expect(html).toContain("Setup quality");
    expect(html).toContain("90");
    expect(html).toContain("Liquidity");
    expect(html).toContain("71");
    expect(html).toContain("Unavailable");
    expect(html).toContain("Why Orion cares");
    expect(html).toContain("Key risk");
    expect(html).toContain("Selected");
    expect(html).not.toContain("0%");
  });

  it("keeps secondary candidates compact while preserving evidence labels", () => {
    const html = renderToStaticMarkup(
      <CompactCandidate item={{ ...candidate, ticker: "CVS", directional_bias: "bearish" }} selected={false} onSelect={() => {}} />
    );

    expect(html).toContain("CVS");
    expect(html).toContain("bearish");
    expect(html).toContain("Setup");
    expect(html).toContain("Liquidity");
    expect(html).not.toContain("Why Orion cares");
  });
});
