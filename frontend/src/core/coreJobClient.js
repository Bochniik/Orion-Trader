import { startCoreJob, getCoreJob, cancelCoreJob } from "../api/api";

function aborted() { return new DOMException("Analysis cancelled", "AbortError"); }
export function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(aborted()); return; }
    const stop = () => { clearTimeout(timer); reject(aborted()); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", stop); resolve(); }, ms);
    signal?.addEventListener("abort", stop, { once: true });
  });
}

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clamp(value, low = 0, high = 100) {
  return Math.max(low, Math.min(high, value));
}

function premarketDirectionalLayer(result) {
  const mode = String(
    result?.session_mode || result?.market_session || result?.session || ""
  ).toLowerCase();

  if (mode !== "premarket") return {};

  const source = result?.premarket?.analysis || result?.premarket || result?.analysis || {};
  const status = String(result?.status || source?.analysis_status || "").toLowerCase();
  const hasFullHistory =
    result?.premarket?.full_intraday_history === true ||
    source?.full_intraday_history === true ||
    status === "full_premarket_analysis";

  const direction = String(
    result?.direction || source?.direction || "neutral"
  ).toLowerCase();

  const score = finite(result?.premarket_score ?? result?.orion_score ?? source?.score);
  const technical = finite(source?.technical_component);
  const quality = finite(source?.data_quality_component);
  const volume = finite(source?.volume_component);

  if (!hasFullHistory || score === null || score <= 0) {
    return {
      opening_outlook: "WAIT",
      directional_conviction: null,
      forecast_horizon: "OPEN -> FIRST 30 MIN",
      forecast_available: false,
      forecast_semantics:
        "A directional premarket outlook requires usable current premarket minute OHLCV. A point snapshot is not treated as a forecast.",
    };
  }

  const evidence = [
    [technical, 0.50],
    [quality, 0.20],
    [volume, 0.15],
    [score, 0.15],
  ].filter(([value]) => value !== null);

  const weight = evidence.reduce((sum, [, w]) => sum + w, 0);
  let conviction = weight
    ? evidence.reduce((sum, [value, w]) => sum + value * w, 0) / weight
    : score;

  if (direction === "neutral") conviction = Math.min(conviction, 49);
  conviction = Math.round(clamp(conviction, 0, 95));

  return {
    opening_outlook:
      direction === "bullish" ? "UP BIAS" :
      direction === "bearish" ? "DOWN BIAS" :
      "NEUTRAL",
    directional_conviction: conviction,
    forecast_horizon: "OPEN -> FIRST 30 MIN",
    forecast_available: direction !== "neutral",
    forecast_semantics:
      "Directional conviction is a 0-100 evidence-strength score from premarket structure, data quality, activity and setup quality. It is not a calibrated probability of profit.",
  };
}

export function normalizeCoreResult(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) return result;

  const modelDirection = String(result.direction || "").trim();
  const finalDecision = String(result.decision || modelDirection || "").trim();
  const strategyBias = result.strategy_bias ?? result.bias ?? null;
  const preservedModelDirection = result.model_direction ?? (modelDirection || null);

  return {
    ...result,
    ...premarketDirectionalLayer(result),
    ticker: String(result.ticker || result.symbol || "").trim().toUpperCase(),
    strategy_bias: strategyBias,
    model_direction: preservedModelDirection,
    // The Dashboard historically read `bias` as the main conclusion. Do not let
    // a lower-level strategy/model vote masquerade as Orion's final decision.
    bias: finalDecision || result.bias || null,
    direction: modelDirection || finalDecision || null,
    decision: finalDecision || null,
    reasons: Array.isArray(result.reasons) ? result.reasons : [],
    warnings: Array.isArray(result.warnings) ? result.warnings : [],
  };
}

export async function runCoreJob(body, { signal, onProgress = () => {} } = {},
  api = { start: startCoreJob, get: getCoreJob, cancel: cancelCoreJob, wait: pause }) {
  let job;
  try {
    // Admission can wait briefly for a cancelled task's in-flight stage to exit.
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (signal?.aborted) throw aborted();
      try { job = await api.start(body); break; }
      catch (error) {
        if (error.status !== 409 || attempt === 29) throw error;
        onProgress("Waiting for the previous review to finish stopping...");
        await api.wait(1000, signal);
      }
    }
    // Do not abort the POST before we know its job ID: otherwise a response
    // arriving after navigation could leave uncancellable server work behind.
    while (true) {
      if (signal?.aborted) throw aborted();
      onProgress(job.stage);
      if (job.state === "completed") return normalizeCoreResult(job.result);
      if (!["queued", "running"].includes(job.state)) throw new Error(job.stage || "The review stopped.");
      await api.wait(800, signal);
      if (signal?.aborted) throw aborted();
      job = await api.get(job.id, { signal });
    }
  } finally {
    // Also request cancellation after a polling failure, not just a UI abort.
    if (job && ["queued", "running"].includes(job.state)) {
      try { await api.cancel(job.id); } catch { /* timeout/logout remains a server-side stop boundary */ }
    }
  }
}
