function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function probability(value) {
  const number = finite(value);
  if (number === null) return "N/A";
  return `${Math.round((Math.abs(number) <= 1 ? number * 100 : number))}%`;
}

function signedPercent(value) {
  const number = finite(value);
  if (number === null) return "N/A";
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function PremarketResearchForecast({ research }) {
  if (research?.available !== true) return null;

  const signals = research?.signals || {};
  const preferred = signals?.premarket_5m || signals?.premarket_15m || null;
  if (!preferred) return null;

  const direction = String(preferred?.direction || "NO_TRADE").replaceAll("_", " ");
  const rawDirection = String(preferred?.raw_direction || "N/A");
  const researchGate = preferred?.research_gate_passed === true;

  return (
    <section className="core-scan-details" aria-label="Premarket short-horizon research forecast">
      <strong>Premarket directional research · {preferred?.window_label || "NEXT 5 MIN (PREMARKET)"}</strong>
      <p>
        {researchGate
          ? `${rawDirection} research bias passed the current research gate.`
          : `Current model state: ${direction}. The research gate has not been passed.`}
        {" "}This is a premarket-only research forecast, not an opening signal or trade instruction.
      </p>
      <div className="orion-mini-metric-grid">
        <div><small>Research direction</small><strong>{direction}</strong></div>
        <div><small>UP / DOWN</small><strong>{probability(preferred?.probability_up)} / {probability(preferred?.probability_down)}</strong></div>
        <div><small>Direction confidence</small><strong>{probability(preferred?.direction_confidence)}</strong></div>
        <div><small>Predicted move</small><strong>{signedPercent(preferred?.predicted_return_pct)}</strong></div>
      </div>
      <small>
        Model {research?.model_version || "premarket_directional_v5_hybrid_return"} · SIP causal snapshot · research only.
      </small>
    </section>
  );
}

export default function PremarketPredictiveDiagnostics({ analysis }) {
  const predictive = analysis?.predictive_outlook || {};
  const signal = predictive?.signals?.open_5m || null;
  const research = predictive?.premarket_research || analysis?.premarket_short_horizon_outlook || null;
  const gate = signal?.gate || {};
  const feed = String(analysis?.predictive_feed || analysis?.feed || "unknown").toUpperCase();
  const edgeThreshold = finite(gate?.edge_threshold);
  const directionThreshold = finite(gate?.direction_threshold);
  const imputed = finite(signal?.imputed_feature_count);
  const reason = predictive?.reason || signal?.reason || (signal?.actionable ? "validated_signal" : "unavailable");

  return (
    <>
      <PremarketResearchForecast research={research} />
      <details className="core-scan-details">
        <summary>Opening-model diagnostics</summary>
        <p>
          Model: {predictive?.model_version || "premarket_predictive_v3_hierarchical"}. Feed: {feed}. Opening actionable: {signal?.actionable ? "YES" : "NO"}.
        </p>
        <p>
          Gate: edge {edgeThreshold === null ? "N/A" : probability(edgeThreshold)} minimum; direction confidence {directionThreshold === null ? "N/A" : probability(directionThreshold)} minimum.
        </p>
        <p>
          Current opening edge: {signal ? probability(signal.edge_probability) : "N/A"}; direction confidence: {signal ? probability(signal.direction_confidence) : "N/A"}; imputed features: {imputed === null ? "N/A" : Math.round(imputed)}.
        </p>
        <p>Status: {String(reason).replaceAll("_", " ").toUpperCase()}.</p>
      </details>
    </>
  );
}
