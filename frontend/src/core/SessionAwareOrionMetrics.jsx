import { ArrowRight, Clock3, Moon, ShieldCheck, Sunrise, Zap } from "lucide-react";

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function pct(value) {
  const number = finite(value);
  if (number === null) return "N/A";
  const normalized = Math.abs(number) <= 1 ? number * 100 : number;
  const sign = normalized > 0 ? "+" : "";
  return `${sign}${normalized.toFixed(2)}%`;
}

function score(value) {
  const number = finite(value);
  return number === null ? "N/A" : Math.round(number);
}

function probability(value) {
  const number = finite(value);
  if (number === null) return "N/A";
  const normalized = Math.abs(number) <= 1 ? number * 100 : number;
  return `${Math.round(normalized)}%`;
}

function riskLabel(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  if (typeof value === "string") return value;
  const number = finite(value);
  if (number === null) return "N/A";
  const normalized = number <= 1 ? number * 100 : number;
  if (normalized < 33) return "Low";
  if (normalized < 66) return "Moderate";
  return "High";
}

function scoreRingStyle(value) {
  const number = finite(value);
  const progress = number === null ? 0 : Math.max(0, Math.min(100, number));
  return { "--orion-score-progress": `${progress}%` };
}

export function MarketSessionBadge({ session, status }) {
  const mode = String(session || "").toLowerCase();
  let label = "SESSION UNKNOWN";
  let icon = <Clock3 size={12} />;

  if (mode === "regular" || mode === "regular_hours" || status === "ready") {
    label = "MARKET OPEN";
    icon = <Zap size={12} />;
  } else if (mode === "premarket" || status === "premarket_research") {
    label = "PRE-MARKET";
    icon = <Sunrise size={12} />;
  } else if (mode === "after_hours" || status === "after_hours_research") {
    label = "AFTER HOURS";
    icon = <Moon size={12} />;
  } else if (mode === "closed" || status === "market_closed") {
    label = "MARKET CLOSED";
    icon = <Clock3 size={12} />;
  }

  return (
    <span className={`orion-session-badge orion-session-${mode || "unknown"}`}>
      {icon}
      {label}
    </span>
  );
}

export function PremarketResearchStrip({ research, onAnalyze }) {
  const items = Array.isArray(research?.items) ? research.items : [];
  if (!items.length) return null;

  return (
    <section className="premarket-research-strip" aria-label="Premarket Orion research">
      <div className="premarket-research-strip-heading">
        <div>
          <span className="core-eyebrow">PRE-MARKET ORION</span>
          <strong>Premarket research candidates</strong>
        </div>
        <small>Opening confirmation required</small>
      </div>

      <div className="premarket-research-strip-items">
        {items.slice(0, 5).map((item) => {
          const ticker = item?.ticker || item?.symbol;
          const pmScore =
            item?.premarket_score ?? item?.analysis?.score ?? item?.score ?? null;
          const direction =
            item?.opening_outlook ??
            item?.direction ??
            item?.analysis?.direction ??
            "neutral";

          return (
            <button
              type="button"
              key={ticker}
              className="premarket-research-chip"
              onClick={() => ticker && onAnalyze?.(ticker)}
              disabled={!ticker}
            >
              <span>
                <strong>{ticker || "N/A"}</strong>
                <small>{String(direction || "neutral").toUpperCase()}</small>
              </span>
              <span>
                <b>{score(pmScore)}</b>
                <small>PM score</small>
              </span>
              <span>
                <b>{item?.directional_conviction != null ? `${Math.round(item.directional_conviction)}/100` : "Research"}</b>
                <small>Conviction</small>
              </span>
              <ArrowRight size={13} />
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ClosedMetrics({ analysis, afterHours = false }) {
  const price =
    finite(analysis?.price) ??
    finite(analysis?.reference_price) ??
    finite(analysis?.quote?.price) ??
    finite(analysis?.evidence?.quote?.price);

  const lastScore =
    finite(analysis?.last_regular_orion_score) ??
    finite(analysis?.orion_score) ??
    finite(analysis?.score);

  return (
    <div className="orion-session-metrics orion-session-metrics-closed">
      <div className="orion-session-message">
        <Clock3 size={18} />
        <div>
          <strong>{afterHours ? "After-hours research mode" : "Market is closed"}</strong>
          <p>
            Live regular-session scoring is paused. Orion can still summarize company,
            news, chart and latest completed-session context.
          </p>
        </div>
      </div>

      <div className="orion-mini-metric-grid">
        <div>
          <small>Latest price</small>
          <strong>{price === null ? "N/A" : `$${price.toFixed(2)}`}</strong>
        </div>
        <div>
          <small>Last regular score</small>
          <strong>{lastScore === null ? "N/A" : `${Math.round(lastScore)} / 100`}</strong>
        </div>
      </div>
    </div>
  );
}

function PremarketMetrics({ analysis }) {
  const pmScore =
    analysis?.premarket_score ??
    analysis?.premarket?.analysis?.score ??
    analysis?.analysis?.score ??
    analysis?.orion_score ??
    null;

  const outlook =
    analysis?.opening_outlook ||
    (analysis?.direction === "bullish"
      ? "UP BIAS"
      : analysis?.direction === "bearish"
        ? "DOWN BIAS"
        : "WAIT");

  const conviction = finite(analysis?.directional_conviction);
  const forecastAvailable = analysis?.forecast_available === true;
  const horizon = analysis?.forecast_horizon || "OPEN -> FIRST 30 MIN";
  const pmPrice =
    finite(analysis?.premarket_price) ??
    finite(analysis?.premarket?.premarket_price) ??
    finite(analysis?.analysis?.premarket_price);

  return (
    <div className="orion-session-metrics orion-session-metrics-premarket">
      <div className="orion-premarket-score">
        <div className="orion-score-ring" style={scoreRingStyle(pmScore)}>
          <div>
            <strong>{score(pmScore)}</strong>
            <span>/100</span>
          </div>
        </div>

        <div>
          <small>Premarket Orion Score</small>
          <strong>{forecastAvailable ? outlook : "WAIT"}</strong>
          <p>Setup quality plus directional opening outlook; not probability of profit.</p>
        </div>
      </div>

      <div className="orion-mini-metric-grid">
        <div>
          <small>Opening outlook</small>
          <strong>{forecastAvailable ? outlook : "INSUFFICIENT DATA"}</strong>
        </div>
        <div>
          <small>Directional conviction</small>
          <strong>{conviction === null ? "N/A" : `${Math.round(conviction)} / 100`}</strong>
        </div>
        <div>
          <small>Forecast window</small>
          <strong>{forecastAvailable ? horizon : "WAIT FOR DATA"}</strong>
        </div>
        <div>
          <small>Premarket price</small>
          <strong>{pmPrice === null ? "N/A" : `$${pmPrice.toFixed(2)}`}</strong>
        </div>
      </div>
    </div>
  );
}

function RegularMetrics({ analysis }) {
  const orionScore =
    analysis?.orion_score ?? analysis?.score ?? analysis?.final_score ?? analysis?.quality_score ?? null;
  const adjusted =
    analysis?.adjusted_orion_score ?? analysis?.adjusted_score ?? analysis?.confidence_score ?? analysis?.confidence ?? null;
  const up =
    analysis?.up_probability ?? analysis?.probability_up ?? analysis?.bullish_probability ?? analysis?.long_probability ?? null;
  const down =
    analysis?.down_probability ?? analysis?.probability_down ?? analysis?.bearish_probability ?? analysis?.short_probability ?? null;
  const manipulation =
    analysis?.manipulation_risk ?? analysis?.manipulationRisk ?? analysis?.risk?.manipulation ?? null;

  return (
    <div className="orion-session-metrics">
      <div className="orion-premarket-score">
        <div className="orion-score-ring" style={scoreRingStyle(orionScore)}>
          <div>
            <strong>{score(orionScore)}</strong>
            <span>/100</span>
          </div>
        </div>

        <div>
          <small>Orion Score</small>
          <strong>{score(adjusted)} adjusted</strong>
          <p>Unified regular-session research score.</p>
        </div>
      </div>

      <div className="orion-mini-metric-grid">
        <div>
          <small>Up probability</small>
          <strong>{probability(up)}</strong>
        </div>
        <div>
          <small>Down probability</small>
          <strong>{probability(down)}</strong>
        </div>
        <div>
          <small>Manipulation risk</small>
          <strong>{riskLabel(manipulation)}</strong>
        </div>
        <div>
          <small>Integrity</small>
          <strong><ShieldCheck size={14} /> ACTIVE</strong>
        </div>
      </div>
    </div>
  );
}

export default function SessionAwareOrionMetrics({ analysis, session, busy = false }) {
  if (busy) {
    return (
      <div className="orion-session-metrics">
        <div className="orion-session-message">
          <span className="core-loading-dot" />
          <div>
            <strong>Orion is calculating...</strong>
            <p>Session-aware research is running for the selected stock.</p>
          </div>
        </div>
      </div>
    );
  }

  const mode = String(
    session ||
      analysis?.session_mode ||
      analysis?.market_session ||
      analysis?.session ||
      ""
  ).toLowerCase();

  if (mode === "premarket") return <PremarketMetrics analysis={analysis || {}} />;
  if (mode === "closed") return <ClosedMetrics analysis={analysis || {}} />;
  if (mode === "after_hours") return <ClosedMetrics analysis={analysis || {}} afterHours />;
  return <RegularMetrics analysis={analysis || {}} />;
}
