import { describe, expect, it } from "vitest";

import { normalizeCoreResult } from "./coreJobClient";


describe("normalizeCoreResult premarket forecasts", () => {
  it("surfaces V5 short-horizon research instead of replacing it with score heuristics", () => {
    const result = normalizeCoreResult({
      ticker: "AMD",
      session_mode: "premarket",
      premarket_score: 62,
      forecast_available: false,
      opening_outlook: "WAIT",
      directional_conviction: null,
      predictive_outlook: {
        available: false,
        reason: "trained_hierarchical_model_artifact_missing",
        signals: {},
        premarket_research: {
          available: true,
          actionable: false,
          research_only: true,
          signals: {
            premarket_5m: {
              window_label: "NEXT 5 MIN (PREMARKET)",
              raw_direction: "UP",
              direction: "UP",
              probability_up: 0.63,
              probability_down: 0.37,
              direction_confidence: 0.63,
              predicted_return_pct: 0.12,
            },
          },
        },
      },
    });

    expect(result.forecast_available).toBe(true);
    expect(result.forecast_actionable).toBe(false);
    expect(result.forecast_scope).toBe("premarket_research");
    expect(result.opening_outlook).toBe("PREMARKET UP");
    expect(result.directional_conviction).toBe(63);
    expect(result.forecast_horizon).toBe("NEXT 5 MIN (PREMARKET)");
    expect(result.premarket_probability_up).toBe(63);
    expect(result.premarket_probability_down).toBe(37);
    expect(result.premarket_predicted_return_pct).toBe(0.12);
    expect(result.setup_summary).toContain("Research only");
    expect(result.forecast_semantics).toContain("does not replace or imply a validated opening forecast");
  });

  it("preserves a real backend opening forecast when one exists", () => {
    const result = normalizeCoreResult({
      ticker: "AMD",
      session_mode: "premarket",
      forecast_available: true,
      forecast_actionable: true,
      opening_outlook: "UP BIAS",
      directional_conviction: 71,
      forecast_horizon: "OPEN -> FIRST 5 MIN",
      predictive_outlook: {
        available: true,
        signals: {
          open_5m: {
            actionable: true,
            direction: "UP",
            direction_confidence: 0.71,
          },
        },
        premarket_research: {
          available: true,
          signals: {
            premarket_5m: {
              raw_direction: "DOWN",
              probability_up: 0.42,
              probability_down: 0.58,
              direction_confidence: 0.58,
            },
          },
        },
      },
    });

    expect(result.forecast_available).toBe(true);
    expect(result.forecast_actionable).toBe(true);
    expect(result.opening_outlook).toBe("UP BIAS");
    expect(result.directional_conviction).toBe(71);
    expect(result.forecast_horizon).toBe("OPEN -> FIRST 5 MIN");
    expect(result.forecast_scope).toBe("opening");
  });

  it("fails closed instead of deriving conviction from the Premarket Orion Score", () => {
    const result = normalizeCoreResult({
      ticker: "AMD",
      session_mode: "premarket",
      premarket_score: 88,
      direction: "bullish",
      forecast_available: false,
      predictive_outlook: {
        available: false,
        signals: {},
        premarket_research: {
          available: false,
          signals: {},
        },
      },
    });

    expect(result.forecast_available).toBe(false);
    expect(result.forecast_actionable).toBe(false);
    expect(result.directional_conviction).toBeNull();
    expect(result.forecast_scope).toBe("unavailable");
  });
});
