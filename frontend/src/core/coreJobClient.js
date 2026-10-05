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

function probabilityPercent(value) {
  const number = finite(value);
  if (number === null) return null;
  const normalized = Math.abs(number) <= 1 ? number * 100 : number;
  return clamp(normalized, 0, 100);
}

function premarketDirectionalLayer(result) {
  const mode = String(
    result?.session_mode || result?.market_session || result?.session || ""
  ).toLowerCase();

  if (mode !== "premarket") return {};

  // Never replace a real backend opening forecast with a client-side heuristic.
  // The backend is the authority for validated opening-model semantics.
  if (result?.forecast_available === true) {
    return {
      forecast_scope: result?.forecast_scope || "opening",
      forecast_semantics:
        result?.forecast_semantics ||
        "Validated opening-model forecast supplied by the Orion backend.",
    };
  }

  const predictive =
    result?.predictive_outlook || result?.premarket?.predictive_outlook || {};
  const research = predictive?.premarket_research || {};
  const signals = research?.signals && typeof research.signals === "object"
    ? research.signals
    : {};

  const target = ["premarket_5m", "premarket_15m", "premarket_30m"]
    .find((name) => signals?.[name] && typeof signals[name] === "object");
  const signal = target ? signals[target] : null;

  if (research?.available === true && signal) {
    const confidence = probabilityPercent(signal?.direction_confidence);
    const probabilityUp = probabilityPercent(signal?.probability_up);
    const probabilityDown = probabilityPercent(signal?.probability_down);
    const rawDirection = String(
      signal?.raw_direction || signal?.direction || ""
    ).toUpperCase();
    const direction = rawDirection === "UP" || rawDirection === "DOWN"
      ? rawDirection
      : "NEUTRAL";
    const horizon =
      signal?.window_label ||
      (target === "premarket_5m"
        ? "NEXT 5 MIN (PREMARKET)"
        : target === "premarket_15m"
          ? "NEXT 15 MIN (PREMARKET)"
          : "NEXT 30 MIN (PREMARKET)");
    const predictedReturn = finite(signal?.predicted_return_pct);
    const probabilityText =
      probabilityUp !== null && probabilityDown !== null
        ? `UP ${Math.round(probabilityUp)}% / DOWN ${Math.round(probabilityDown)}%`
        : "directional probabilities available in model diagnostics";
    const moveText = predictedReturn === null
      ? ""
      : `; expected move ${predictedReturn >= 0 ? "+" : ""}${predictedReturn.toFixed(2)}%`;

    return {
      // Dashboard compatibility fields. Scope/actionability explicitly prevent
      // this research forecast from being treated as an opening trade signal.
      forecast_available: true,
      forecast_actionable: false,
      forecast_scope: "premarket_research",
      forecast_target: target,
      opening_outlook: `PREMARKET ${direction}`,
      directional_conviction:
        confidence === null ? null : Math.round(confidence * 100) / 100,
      forecast_horizon: horizon,
      premarket_probability_up: probabilityUp,
      premarket_probability_down: probabilityDown,
      premarket_predicted_return_pct: predictedReturn,
      forecast_semantics:
        "Research-only Premarket V5 short-horizon forecast. It does not replace or imply a validated opening forecast.",
      setup_summary:
        `Premarket V5 research currently leans ${direction} over ${horizon}. ` +
        `${probabilityText}${moveText}. Research only; the opening forecast remains fail-closed until separately validated.`,
    };
  }

  // No model output: remain fail-closed. In particular, do not manufacture a
  // directional conviction from Premarket Orion Score components.
  return {
    opening_outlook: result?.opening_outlook || "WAIT",
    directional_conviction: result?.directional_conviction ?? null,
    forecast_horizon: result?.forecast_horizon ?? null,
    forecast_available: false,
    forecast_actionable: false,
    forecast_scope: "unavailable",
    forecast_semantics:
      result?.forecast_semantics ||
      "No validated opening or Premarket V5 research forecast is currently available.",
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
