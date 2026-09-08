import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import RiskProfilePanel from "./RiskProfilePanel";
import TradeRecommendation from "./TradeRecommendation";


const profiles = [
  { mode: "conservative", label: "Conservative", summary: "Shares only", risk_percent: 0.35, max_position_percent: 10, max_instrument_leverage: 1, daily_loss_limit_percent: 1, minimum_setup_quality: 72, minimum_risk_reward: 1.6 },
  { mode: "balanced", label: "Balanced", summary: "Moderate unlevered budget", risk_percent: 0.5, max_position_percent: 15, max_instrument_leverage: 1, daily_loss_limit_percent: 1, minimum_setup_quality: 75, minimum_risk_reward: 1.7 },
  { mode: "aggressive", label: "Aggressive", summary: "Higher unlevered budget", risk_percent: 0.75, max_position_percent: 20, max_instrument_leverage: 1, daily_loss_limit_percent: 1.5, minimum_setup_quality: 78, minimum_risk_reward: 1.8 },
];


describe("risk recommendation UI", () => {
  it("shows all three persisted modes and deterministic limits", () => {
    const html = renderToStaticMarkup(<RiskProfilePanel
      data={{ selected_mode: "balanced", profile: profiles[1], available_profiles: profiles }}
      saving={false}
      onSelect={() => {}}
    />);

    expect(html).toContain("Conservative");
    expect(html).toContain("Balanced");
    expect(html).toContain("Aggressive");
    expect(html).toContain("DETERMINISTIC RISK ENGINE");
    expect(html).toContain("1x · unlevered");
  });

  it("labels the current plan as unlevered and execution as external", () => {
    const html = renderToStaticMarkup(<TradeRecommendation plan={{
      status: "qualified",
      instrument: "REAL_SHARES",
      instrument_label: "Unlevered real shares only",
      setup_quality: 92,
      entry_price: 100,
      stop_loss: 98,
      take_profit: 105,
      risk_reward: 2.33,
      quantity: 150,
      estimated_max_loss: 322.5,
      risk_percent: 0.5,
      notional_exposure: 15000,
      exposure_percent: 15,
      estimated_margin: 15000,
      suggested_leverage: 1,
      gates: [],
      warnings: ["Verify in the external broker."],
    }} />);

    expect(html).toContain("Unlevered real shares only");
    expect(html).toContain("External execution only");
    expect(html).toContain("setup quality");
    expect(html).not.toContain("Buy now");
  });

  it("shows concrete watch levels instead of a generic incomplete plan", () => {
    const html = renderToStaticMarkup(<TradeRecommendation plan={{
      status: "awaiting_trigger",
      instrument: "NO_TRADE",
      instrument_label: "No trade — wait for the breakout trigger",
      setup_quality: 81,
      current_price: 98.5,
      entry_price: 100,
      breakout_price: 100,
      stop_loss: 97,
      take_profit: 106,
      risk_reward: 2,
      instrument_currency: "USD",
      trigger_status: "waiting_for_breakout",
      level_summary: "A concrete breakout level is available, but price and volume have not confirmed it yet.",
      gates: [{ name: "entry_trigger", passed: false, detail: "Wait for price and volume." }],
      warnings: [],
    }} />);

    expect(html).toContain("Watch — waiting for breakout");
    expect(html).toContain("Breakout trigger");
    expect(html).toContain("$100.00");
    expect(html).toContain("Protective stop");
    expect(html).toContain("Research target");
    expect(html).not.toContain("plan incomplete");
    expect(html).not.toContain("Risk ceiling");
  });
});
