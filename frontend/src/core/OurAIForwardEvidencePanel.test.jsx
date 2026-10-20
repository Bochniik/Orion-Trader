import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import OurAIForwardEvidencePanel, { ForwardEvidenceSummary } from "./OurAIForwardEvidencePanel";

const evidence = {
  status: "available",
  source: "ourai_verified_forward_journal",
  experiment: "frozen_v3_magnitude_15m",
  mode: "RESEARCH_SHADOW_ONLY",
  direction_available: false,
  trading_enabled: false,
  as_of: "2026-10-20T14:05:00Z",
  champion_mae_bps: 8.706,
  linear_mae_bps: 9.792,
  null_mae_bps: 10.699,
  prediction_count: 739,
  resolution_count: 728,
  pending_count: 11,
  overdue_pending_count: 11,
  symbols: {
    NVDA: { resolved: 99, champion_mae_bps: 10.996, linear_mae_bps: 11.361, null_mae_bps: 11.168 },
    TSLA: { resolved: 100, champion_mae_bps: 10.587, linear_mae_bps: 11.624, null_mae_bps: 9.543 },
  },
  latest_by_symbol: {
    NVDA: {
      symbol: "NVDA",
      expected_magnitude_bps: 12.4,
      predicted_at: "2026-10-20T14:00:20Z",
      resolved: false,
    },
  },
};

describe("OurAI verified forward evidence panel", () => {
  it("starts with a read-only loading state instead of invented metrics", () => {
    const html = renderToStaticMarkup(<OurAIForwardEvidencePanel selectedTicker="NVDA" />);
    expect(html).toContain("Loading local OurAI evidence");
    expect(html).not.toContain("8.71 bps");
  });

  it("renders authenticated and server-validated magnitude-only snapshot", () => {
    const html = renderToStaticMarkup(<ForwardEvidenceSummary evidence={evidence} selectedTicker="NVDA" />);
    expect(html).toContain("Journal validated");
    expect(html).toContain("8.71 bps");
    expect(html).toContain("9.79 bps");
    expect(html).toContain("10.70 bps");
    expect(html).toContain("728 / 11");
    expect(html).toContain("11 overdue pending");
    expect(html).toContain("10.59 bps"); // TSLA
    expect(html).toContain("9.54 bps"); // TSLA null baseline is better than V3
    expect(html).toContain("Latest NVDA forecast");
    expect(html).toContain("12.40 bps");
    expect(html).toContain("Awaiting settlement");
    expect(html).toContain("not independent proof");
    expect(html).toContain("No direction, position sizing, trading action");
  });

  it("withholds all evidence when bridge is disabled or unavailable", () => {
    for (const status of ["disabled", "unavailable"]) {
      const html = renderToStaticMarkup(
        <ForwardEvidenceSummary evidence={{ status, champion_mae_bps: 8.7 }} selectedTicker="NVDA" />
      );
      expect(html).not.toContain("8.70 bps");
      expect(html).not.toContain("Journal validated");
      expect(html).toContain(status === "disabled" ? "Local OurAI bridge is disabled" : "No verified forward figures available");
    }
  });

  it("fails closed for an available state with incorrect evidence semantics", () => {
    for (const mutation of [
      { direction_available: true },
      { trading_enabled: true },
      { source: "unverified_local_file" },
      { experiment: "directional_model" },
    ]) {
      const html = renderToStaticMarkup(<ForwardEvidenceSummary evidence={{ ...evidence, ...mutation }} />);
      expect(html).not.toContain("8.71 bps");
      expect(html).toContain("Evidence unavailable");
    }
  });

  it("keeps missing metrics unavailable and does not infer direction from absolute movement", () => {
    const html = renderToStaticMarkup(
      <ForwardEvidenceSummary evidence={{
        ...evidence,
        champion_mae_bps: null,
        latest_by_symbol: { NVDA: { ...evidence.latest_by_symbol.NVDA, expected_magnitude_bps: null } },
      }} selectedTicker="NVDA" />
    );
    expect(html).toContain("Unavailable");
    expect(html).not.toContain("8.71 bps");
    expect(html).not.toContain("12.40 bps");
    expect(html).toContain("not an indication of direction");
  });

  it("displays another selected symbol only when matching latest identity is present", () => {
    const html = renderToStaticMarkup(<ForwardEvidenceSummary evidence={evidence} selectedTicker="AAPL" />);
    expect(html).not.toContain("Latest NVDA forecast");
  });
});
