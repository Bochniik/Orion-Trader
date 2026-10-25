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
      target_due_at: "2026-10-20T14:15:00Z",
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
    const html = renderToStaticMarkup(<ForwardEvidenceSummary evidence={evidence} selectedTicker="NVDA" now={Date.parse("2026-10-20T14:10:00Z")} />);
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
    expect(html).not.toContain("Overdue settlement");
    expect(html).not.toContain("Historical snapshot");
    expect(html).toContain("not independent proof");
    expect(html).toContain("No direction, position sizing, trading action");
  });

  it("labels an aged journal snapshot and overdue pending forecast without claiming model failure", () => {
    const html = renderToStaticMarkup(
      <ForwardEvidenceSummary evidence={evidence} selectedTicker="NVDA" now={Date.parse("2026-10-25T07:00:00Z")} />
    );
    expect(html).toContain("Historical snapshot — not current market evidence");
    expect(html).toContain("Historical forecast, not a live signal");
    expect(html).toContain("Overdue settlement");
    expect(html).toContain("unresolved observation, not a model accuracy verdict");
    expect(html).not.toContain("Awaiting settlement");
    expect(html).not.toContain("P(UP)");
  });

  it("does not call a settled historical forecast overdue", () => {
    const settled = {
      ...evidence,
      latest_by_symbol: {
        NVDA: { ...evidence.latest_by_symbol.NVDA, resolved: true },
      },
    };
    const html = renderToStaticMarkup(
      <ForwardEvidenceSummary evidence={settled} selectedTicker="NVDA" now={Date.parse("2026-10-25T07:00:00Z")} />
    );
    expect(html).toContain("Historical forecast, not a live signal");
    expect(html).toContain("Settled");
    expect(html).not.toContain("Overdue settlement");
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

  it("distinguishes connection, HTTP and evidence validation failures without publishing predictions", () => {
    const cases = [
      ["upstream_connection_failure", "data-availability outage"],
      ["upstream_http_failure", "HTTP error"],
      ["invalid_upstream_evidence", "failed evidence validation"],
    ];
    for (const [reason, label] of cases) {
      const html = renderToStaticMarkup(
        <ForwardEvidenceSummary evidence={{
          ...evidence,
          status: "unavailable",
          unavailable_reason: reason,
        }} selectedTicker="NVDA" />
      );
      expect(html).toContain(label);
      expect(html).toContain("No verified forward figures available");
      expect(html).not.toContain("8.71 bps");
      expect(html).not.toContain("Latest NVDA forecast");
      expect(html).not.toContain("Journal validated");
    }
  });

  it("never echoes unknown upstream errors or mistakes outages for model scores", () => {
    const html = renderToStaticMarkup(
      <ForwardEvidenceSummary evidence={{
        ...evidence,
        status: "unavailable",
        unavailable_reason: "WinError 10060 token=private",
      }} selectedTicker="NVDA" />
    );
    expect(html).toContain("The local service may be offline");
    expect(html).not.toContain("WinError");
    expect(html).not.toContain("private");
    expect(html).not.toContain("8.71 bps");
    expect(html).not.toContain("Latest NVDA forecast");
  });

  it("fails closed for an available state with incorrect evidence semantics", () => {
    for (const mutation of [
      { direction_available: true },
      { trading_enabled: true },
      { source: "unverified_local_file" },
      { experiment: "directional_model" },
      { mode: "LIVE_TRADING" },
      { mode: undefined },
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


describe("OurAI evidence pending-settlement display", () => {
  it("shows an explicit awaiting-settlement state without fabricating MAE", () => {
    const html = renderToStaticMarkup(
      <ForwardEvidenceSummary evidence={{
        ...evidence,
        resolution_count: 0,
        prediction_count: 11,
        pending_count: 11,
        champion_mae_bps: null,
        linear_mae_bps: null,
        null_mae_bps: null,
        symbols: {},
        latest_by_symbol: {},
      }} />
    );
    expect(html).toContain("Awaiting first settled prediction");
    expect(html).toContain("Unavailable");
    expect(html).not.toContain("8.71 bps");
    expect(html).toContain("No direction, position sizing, trading action");
  });
});
