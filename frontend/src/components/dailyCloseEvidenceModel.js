export function normalizeDailyCloseEvidence(review) {
  const count = Number(review?.sample_size ?? review?.settled_count ?? review?.count ?? 0);
  const rawAccuracy = review?.directional_accuracy_pct ??
    (Number.isFinite(Number(review?.directional_accuracy)) ? Number(review.directional_accuracy) * 100 : null);
  return {
    count: Number.isFinite(count) && count > 0 ? count : 0,
    accuracy: Number.isFinite(Number(rawAccuracy)) ? Number(rawAccuracy) : null,
  };
}
