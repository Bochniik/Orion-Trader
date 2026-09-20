import { describe, expect, it } from "vitest";
import { normalizeDailyCloseEvidence } from "./dailyCloseEvidenceModel";

describe("daily close settled evidence contract", () => {
  it("normalizes overall and per-horizon settled evidence", () => {
    const result = normalizeDailyCloseEvidence({
      session_date: "2026-09-18",
      sample_size: 12,
      directional_accuracy: 0.75,
      brier_score: 0.19,
      binary_log_loss: 0.58,
      false_positives: 2,
      false_negatives: 1,
      by_horizon: [{ horizon: "1h", settled_count: 5, directional_accuracy_pct: 80 }],
    });
    expect(result.sessionDate).toBe("2026-09-18");
    expect(result.sampleSize).toBe(12);
    expect(result.accuracyPct).toBe(75);
    expect(result.horizons).toEqual([expect.objectContaining({ horizon: "1h", sampleSize: 5, accuracyPct: 80 })]);
  });

  it("fails closed instead of inventing settled metrics", () => {
    expect(normalizeDailyCloseEvidence({})).toEqual(expect.objectContaining({
      sampleSize: 0,
      accuracyPct: null,
      brierScore: null,
      logLoss: null,
      horizons: [],
    }));
  });
});
