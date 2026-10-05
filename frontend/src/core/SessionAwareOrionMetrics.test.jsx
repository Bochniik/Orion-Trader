import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import SessionAwareOrionMetrics from "./SessionAwareOrionMetrics";


describe("SessionAwareOrionMetrics premarket states", () => {
  it("does not call usable premarket context insufficient data when only the validated forecast is pending", () => {
    const html = renderToStaticMarkup(
      <SessionAwareOrionMetrics
        session="premarket"
        analysis={{
          session_mode: "premarket",
          premarket_score: 63,
          premarket_price: 101.25,
          full_intraday_history: true,
          forecast_available: false,
          predictive_outlook: {
            available: false,
            reason: "sip_prediction_history_unavailable",
            signals: {},
          },
        }}
      />
    );

    expect(html).toContain("OBSERVING");
    expect(html).toContain("VALIDATED MODEL PENDING");
    expect(html).toContain("AWAITING SIP PREDICTION DATA");
    expect(html).not.toContain("Opening outlook</small><strong>INSUFFICIENT DATA");
  });

  it("renders a validated below-gate prediction without converting it into a trade signal", () => {
    const html = renderToStaticMarkup(
      <SessionAwareOrionMetrics
        session="premarket"
        analysis={{
          session_mode: "premarket",
          premarket_score: 71,
          premarket_price: 102.5,
          forecast_available: true,
          opening_outlook: "WAIT",
          directional_conviction: 61,
          forecast_horizon: "OPEN -> FIRST 5 MIN",
          predictive_outlook: {
            available: true,
            reason: null,
            signals: {
              open_5m: {
                actionable: false,
                direction: "NO_EDGE",
                edge_probability: 0.51,
                direction_confidence: 0.61,
                up_given_edge: 0.61,
                down_given_edge: 0.39,
              },
            },
          },
        }}
      />
    );

    expect(html).toContain("BELOW VALIDATED GATE");
    expect(html).toContain("51%");
    expect(html).toContain("61%");
    expect(html).toContain("61% / 39%");
    expect(html).toContain("NO EDGE");
  });

  it("shows the missing model artifact as a model problem rather than generic insufficient data", () => {
    const html = renderToStaticMarkup(
      <SessionAwareOrionMetrics
        session="premarket"
        analysis={{
          session_mode: "premarket",
          premarket_score: 58,
          full_intraday_history: true,
          predictive_outlook: {
            available: false,
            reason: "trained_hierarchical_model_artifact_missing",
            signals: {},
          },
        }}
      />
    );

    expect(html).toContain("MODEL NOT LOADED");
  });
});
