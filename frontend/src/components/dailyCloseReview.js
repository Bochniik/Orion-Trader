import { API_BASE_URL } from "../api/api";

export async function getDailyCloseReview(options = {}) {
  const response = await fetch(`${API_BASE_URL}/scanner/learning/daily-close-review`, {
    ...options,
    method: "GET",
    credentials: "include",
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = typeof data === "object" ? data?.detail : data;
    throw new Error(detail || `Daily close review unavailable (${response.status})`);
  }
  return data;
}

export function normalizeDailyCloseReview(review) {
  const sampleSize = Number(review?.sample_size ?? review?.count ?? 0);
  const metrics = review?.metrics || review?.summary || review || {};
  const horizons = review?.horizons || review?.by_horizon || metrics?.by_horizon || [];
  return {
    sessionDate: review?.session_date || null,
    sampleSize: Number.isFinite(sampleSize) && sampleSize > 0 ? sampleSize : 0,
    brierScore: finiteOrNull(metrics.brier_score),
    logLoss: finiteOrNull(metrics.log_loss),
    directionalAccuracy: finiteOrNull(metrics.directional_accuracy),
    falsePositives: finiteOrNull(metrics.false_positives),
    falseNegatives: finiteOrNull(metrics.false_negatives),
    horizons: Array.isArray(horizons) ? horizons : Object.values(horizons || {}),
  };
}

function finiteOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
