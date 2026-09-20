import { describe, expect, it } from "vitest";
import { normalizeDailyCloseEvidence } from "./dailyCloseEvidenceModel";

describe("daily close evidence contract", () => {
  it("normalizes settled sample size and fractional directional accuracy", () => {
    expect(normalizeDailyCloseEvidence({ sample_size: 12, directional_accuracy: 0.75 })).toEqual({ count: 12, accuracy: 75 });
  });

  it("fails closed instead of inventing evidence", () => {
    expect(normalizeDailyCloseEvidence({})).toEqual({ count: 0, accuracy: null });
  });
});
