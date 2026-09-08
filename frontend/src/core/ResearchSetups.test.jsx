import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import ResearchSetups, { ResearchSetupCard } from "./ResearchSetups";

const now = Date.parse("2026-09-03T15:30:00Z");
const row = { ticker: "TEST", current_price: 100, data_timestamp: new Date(now).toISOString(), feature_timestamp: new Date(now-60000).toISOString(),
  horizon: "day", direction: "bullish", strategy: "breakout", quality_score: 84, confidence: null,
  entry_zone: [99.9,100.1], stop_loss: 99, target_1: 102, target_2: 103,
  risk_reward: 2, risk_reward_after_costs: 1.8, holding_horizon: {value:60,unit:"minutes"}, market_regime: "bullish_trend",
  liquidity_score: 90, spread_pct: .02, freshness: "delayed", reasons:["Trend confirmed"], warnings:["No proven predictive edge"], setup_id:"fixture" };

describe("Analytical research setup display", () => {
  it("keeps quality distinct from missing model probability", () => {
    const html = renderToStaticMarkup(<ResearchSetupCard row={row} now={now} onAnalyze={()=>{}} />);
    expect(html).toContain("84.0 / 100 · not a probability");
    expect(html).toContain("Model probability unavailable");
    expect(html).not.toContain("84.0%");
    expect(html).toContain("NO TRADE research");
    expect(html).toContain("$102.00");
    expect(html).toContain("$103.00");
    expect(html).toContain("60 minutes");
  });
  it("shows the exact separate forecast horizon and does not claim trade-success probability", () => {
    const html = renderToStaticMarkup(<ResearchSetupCard row={{...row,confidence:72,confidence_horizon:"5m"}} now={now} onAnalyze={()=>{}} />);
    expect(html).toContain("72.0% over 5m · experimental, not trade success");
    expect(html).toContain("Hold 60 minutes");
  });
  it("demotes aged quotes and read failures", () => {
    const render = props => renderToStaticMarkup(<ResearchSetupCard row={row} onAnalyze={()=>{}} {...props}/>);
    expect(render({now:now+121000})).toContain("STALE");
    expect(render({now,error:"network"})).toContain("STALE");
  });
  it("uses existing Analyze and explicit explanation callbacks only", () => {
    const analyze=vi.fn(), explain=vi.fn();
    const card=ResearchSetupCard({row,onAnalyze:analyze,onExplain:explain,now});
    card.props.children[0].props.children[0].props.onClick();
    card.props.children.at(-1).props.onClick();
    expect(analyze).toHaveBeenCalledWith("TEST");
    expect(explain).toHaveBeenCalledWith("fixture");
  });
  it("renders three research horizons, no fake results and no automatic history scans", () => {
    const html=renderToStaticMarkup(<ResearchSetups data={{groups:{day:[],swing:[],long_term:[]}}} now={now} onAnalyze={()=>{}}/>);
    expect(html).toContain("Day Trading");
    expect(html).toContain("Swing Trading");
    expect(html).toContain("Long-Term Investing");
    expect(html).toContain("No qualifying day setups");
    expect(html).toContain("Load outcome history");
    expect(html).not.toContain("BUY");
  });
});
