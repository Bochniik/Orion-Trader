export function finite(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}
export function price(value) {
  return finite(value) ? Number(value).toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: Number(value) < 1 ? 4 : 2 }) : "Unavailable";
}
export function priceZone(values) { return Array.isArray(values) && values.length ? values.map(price).join(" – ") : "Unavailable"; }
export function localTime(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Time unavailable";
}
export function currentDecision(decision, now = Date.now()) {
  if (!decision?.actionable) return decision;
  const horizons = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600 };
  const observed = Date.parse(decision.timestamp), expires = Date.parse(decision.expires_at), quote = Date.parse(decision.model_outputs?.quote_as_of);
  const snapshot = decision.model_outputs?.feature_snapshot;
  const required = ["price_momentum", "atr_14", "realized_volatility", "relative_volume", "index_momentum", "relative_strength_market"];
  const staleSource = decision.model_outputs?.core_validation && required.some(name => {
    const meta = snapshot?.feature_provenance?.[name];
    const asOf = Date.parse(meta?.as_of);
    return meta?.status !== "fresh" || !Number.isFinite(asOf) || asOf > now || now - asOf > 120000;
  });
  const historical = Date.parse(snapshot?.history_timestamp || snapshot?.timestamp || decision.timestamp);
  const stale = staleSource || !Number.isFinite(observed) || !Number.isFinite(expires) || !Number.isFinite(quote)
    || now < observed || now < quote || now >= expires || now - quote > 60000
    || !Number.isFinite(historical) || now < historical
    || now - Math.min(observed, historical) > Math.min(120, horizons[decision.timeframe] || 60) * 1000;
  if (!stale) return decision;
  return { ...decision, actionable: false, decision: "WAIT", direction: "WAIT", status: "expired",
    confidence: null, directional_confidence: null, probability_up: null, probability_down: null,
    probability_neutral: null, model_direction: null, confidence_kind: "unavailable",
    confidence_unavailable_reasons: ["The price, quote or feature snapshot is stale; refresh before using a directional estimate."],
    entry_zone: null, invalidation: null, targets: [], risk_reward: null, expected_move: null,
    warnings: ["This snapshot has expired. Refresh before considering the setup.", ...(decision.warnings || [])] };
}
