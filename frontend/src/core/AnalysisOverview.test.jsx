import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AnalysisOverview, { analysisMetrics } from "./AnalysisOverview";

describe("AnalysisOverview", () => {
  const fixture = {
    ticker: "NVDA",
    company_name: "NVIDIA Corporation",
    sector: "Technology",
    industry: "Semiconductors",
    session_mode: "regular",
    decision: "WAIT",
    orion_score: 62,
    adjusted_orion_score: 58,
    probability_up: 0.66,
    probability_down: 0.34,
    probability_horizon: "30m",
    manipulation_risk: 42,
    reasons: ["Momentum and volume are aligned."],
    warnings: ["Elevated volatility."],
    technical_context: { price: 128.4, rsi: 61.3, relative_volume: 1.8, support: 124, resistance: 132 },
    fundamental_context: { available: true, market_cap: 3_100_000_000_000, fundamental_profile_label: "Semiconductors" },
  };

  it("renders authoritative score, probability and integrity metrics", () => {
    const html = renderToStaticMarkup(<AnalysisOverview analysis={fixture} />);
    expect(html).toContain("Orion Score");
    expect(html).toContain("62");
    expect(html).toContain("58");
    expect(html).toContain("66%");
    expect(html).toContain("34%");
    expect(html).toContain("MEDIUM");
    expect(html).toContain("not proof of illegal manipulation");
    expect(html).toContain("1.80×");
  });

  it("preserves missing probabilities instead of deriving them from a score", () => {
    const metrics = analysisMetrics({ ...fixture, probability_up: null, probability_down: null });
    expect(metrics.orionScore).toBe(62);
    expect(metrics.up).toBeNull();
    expect(metrics.down).toBeNull();
    const html = renderToStaticMarkup(
      <AnalysisOverview analysis={{ ...fixture, probability_up: null, probability_down: null }} />
    );
    expect(html).toContain("validated calibrated model");
  });
});
