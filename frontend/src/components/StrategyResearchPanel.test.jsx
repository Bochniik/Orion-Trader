import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import StrategyResearchPanel from "./StrategyResearchPanel";


const STRATEGY_NAMES = [
  ["trend_momentum", "Trend-following momentum"],
  ["trend_pullback", "Relative-strength trend pullback"],
  ["catalyst_orb", "Catalyst momentum + 5-minute ORB"],
  ["mean_reversion", "Regime-filtered mean reversion"],
  ["volatility_contraction", "Volatility-contraction breakout"],
  ["pairs_trading", "Pairs-trading divergence screen"],
  ["long_term_diversified", "Long-term diversified investing"],
  ["golden_cross", "Golden Cross (50 SMA above 200 SMA)"],
  ["death_cross", "Death Cross (50 SMA below 200 SMA)"],
];

function strategy([id, name], index) {
  return {
    id, name, rank: index + 1, category: "Research", timeframe: "Days to months",
    evidence: "Evidence must be tested after costs.", setup: "Defined setup.",
    trigger: "Defined trigger.", exit: "Defined exit.", status: id === "golden_cross" ? "triggered" : "not_aligned",
    bias: id === "golden_cross" ? "long" : "neutral", score: id === "golden_cross" ? 80 : 20,
    score_meaning: "Rule completion, not probability of profit", summary: "Deterministic research summary.",
    checks: [{ name: "market_regime", passed: id === "golden_cross", available: true, required: true, detail: "SPY regime check." }],
    levels: id === "golden_cross" ? { entry: 101, stop: 96, target: 111, risk_reward: 2 } : { entry: null, stop: null, target: null, risk_reward: null },
    risk_notes: ["Size from risk, not conviction."], limitations: [], evidence_snapshot: {},
  };
}

describe("StrategyResearchPanel", () => {
  it("presents every requested playbook without implying certainty or execution", () => {
    const strategies = STRATEGY_NAMES.map(strategy);
    const html = renderToStaticMarkup(<StrategyResearchPanel
      ticker="AAPL"
      initialData={{
        ticker: "AAPL", peer: null, data_quality: { partial_failure: false },
        strategy_analysis: {
          top_setup: { id: "golden_cross", name: strategies[7].name, score: 80, summary: "Confirmed with filters." },
          strategies,
        },
      }}
      onAskOrion={() => {}}
      onOpenBacktests={() => {}}
    />);

    for (const [, name] of STRATEGY_NAMES) expect(html).toContain(name);
    expect(html.toLowerCase()).toContain("rule completion");
    expect(html).toContain("not a probability of profit");
    expect(html).toContain("Entry trigger");
    expect(html).toContain("Invalidation stop");
    expect(html).toContain("Research only");
    expect(html).toContain("not certainty");
    expect(html).not.toContain("Place order");
  });
});
