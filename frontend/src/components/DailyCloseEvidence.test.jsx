import { describe, expect, it } from "vitest";

function normalize(review) {
  const count = Number(review?.sample_size ?? review?.settled_count ?? review?.count ?? 0);
  const rawAccuracy = review?.directional_accuracy_pct ??
    (Number.isFinite(Number(review?.directional_accuracy)) ? Number(review.directional_accuracy) * 100 : null);
  return { count, accuracy: Number.isFinite(Number(rawAccuracy)) ? Number(rawAccuracy) : null };
}

describe("daily close evidence contract", () => {
  it("normalizes settled sample size and fractional directional accuracy", () => {
    expect(normalize({ sample_size: 12, directional_accuracy: 0.75 })).toEqual({ count: 12, accuracy: 75 });
  });

  it("fails closed instead of inventing evidence", () => {
    expect(normalize({})).toEqual({ count: 0, accuracy: null });
  });
});
