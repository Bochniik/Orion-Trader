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

export default function PremarketPredictiveDiagnostics({ analysis }) {
  const predictive = analysis?.predictive_outlook || {};
  const signal = predictive?.signals?.open_5m || null;
  const gate = signal?.gate || {};
  const feed = String(analysis?.feed || "unknown").toUpperCase();
  const edgeThreshold = finite(gate?.edge_threshold);
  const directionThreshold = finite(gate?.direction_threshold);
  const imputed = finite(signal?.imputed_feature_count);
  const reason = predictive?.reason || signal?.reason || (signal?.actionable ? "validated_signal" : "unavailable");

  return (
    <details className="core-scan-details">
      <summary>Predictive model diagnostics</summary>
      <p>
        Model: {predictive?.model_version || "premarket_predictive_v3_hierarchical"}. Feed: {feed}. Actionable: {signal?.actionable ? "YES" : "NO"}.
      </p>
      <p>
        Gate: edge {edgeThreshold === null ? "N/A" : probability(edgeThreshold)} minimum; direction confidence {directionThreshold === null ? "N/A" : probability(directionThreshold)} minimum.
      </p>
      <p>
        Current edge: {signal ? probability(signal.edge_probability) : "N/A"}; direction confidence: {signal ? probability(signal.direction_confidence) : "N/A"}; imputed features: {imputed === null ? "N/A" : Math.round(imputed)}.
      </p>
      <p>Status: {String(reason).replaceAll("_", " ").toUpperCase()}.</p>
    </details>
  );
}
