import { describe, expect, it } from "vitest";
import { normalizeDailyCloseReview } from "./dailyCloseReview";

describe("normalizeDailyCloseReview", () => {
  it("preserves settled metrics and session provenance", () => {
    const result = normalizeDailyCloseReview({
      session_date: "2026-09-18",
      sample_size: 12,
      metrics: {
        brier_score: 0.18,
        log_loss: 0.51,
        directional_accuracy: 0.75,
        false_positives: 2,
        false_negatives: 1,
      },
      by_horizon: [{ horizon: "1h", sample_size: 4 }],
    });
    expect(result).toMatchObject({
      sessionDate: "2026-09-18",
      sampleSize: 12,
      brierScore: 0.18,
      logLoss: 0.51,
      directionalAccuracy: 0.75,
      falsePositives: 2,
      falseNegatives: 1,
    });
    expect(result.horizons).toHaveLength(1);
  });

  it("does not fabricate metrics for empty or malformed evidence", () => {
    const result = normalizeDailyCloseReview({ sample_size: 0, metrics: { brier_score: "bad" } });
    expect(result.sessionDate).toBeNull();
    expect(result.sampleSize).toBe(0);
    expect(result.brierScore).toBeNull();
    expect(result.directionalAccuracy).toBeNull();
  });
});
