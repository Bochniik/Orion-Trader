const HORIZON_KEYS = ["horizons", "by_horizon", "horizon_results", "results_by_horizon"];

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function first(value, ...fallbacks) {
  if (value !== undefined && value !== null) return value;
  return fallbacks.find((item) => item !== undefined && item !== null);
}

function normalizeAccuracy(row) {
  const pct = finite(first(row?.directional_accuracy_pct, row?.accuracy_pct));
  if (pct !== null) return pct;
  const ratio = finite(first(row?.directional_accuracy, row?.accuracy));
  return ratio === null ? null : ratio * 100;
}

function normalizeRow(row = {}) {
  const count = finite(first(row.sample_size, row.settled_count, row.outcome_count, row.count));
  return {
    horizon: first(row.horizon, row.forecast_horizon, row.label) ?? null,
    sampleSize: count !== null && count > 0 ? count : 0,
    accuracyPct: normalizeAccuracy(row),
    brierScore: finite(row.brier_score),
    logLoss: finite(first(row.binary_log_loss, row.log_loss)),
    falsePositives: finite(row.false_positives),
    falseNegatives: finite(row.false_negatives),
  };
}

export function normalizeDailyCloseEvidence(review) {
  if (!review || typeof review !== "object") return null;

  const overall = normalizeRow(review);
  const rawHorizons = HORIZON_KEYS.map((key) => review[key]).find(Array.isArray) || [];
  const horizons = rawHorizons
    .map(normalizeRow)
    .filter((row) => row.horizon && row.sampleSize > 0);

  return {
    sessionDate: first(review.session_date, review.trading_session, review.latest_settled_session) ?? null,
    ...overall,
    horizons,
  };
}
