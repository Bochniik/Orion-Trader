import { ArrowRight, Clock3, Moon, ShieldCheck, Sunrise, Zap } from "lucide-react";
import PremarketPredictiveDiagnostics from "./PremarketPredictiveDiagnostics";

const finite = (value) => {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const score = (value) => {
  const number = finite(value);
  return number === null ? "N/A" : Math.round(number);
};

const probability = (value) => {
  const number = finite(value);
  if (number === null) return "N/A";
  return `${Math.round((Math.abs(number) <= 1 ? number * 100 : number))}%`;
};

const riskLabel = (value) => {
  if (value === null || value === undefined || value === "") return "N/A";
  if (typeof value === "string") return value;
  const number = finite(value);
  if (number === null) return "N/A";
  const normalized = number <= 1 ? number * 100 : number;
  return normalized < 33 ? "Low" : normalized < 66 ? "Moderate" : "High";
};

const scoreRingStyle = (value) => {
  const number = finite(value);
  const progress = number === null ? 0 : Math.max(0, Math.min(100, number));
  return { "--orion-score-progress": `${progress}%` };
};

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
  }
  return <span className={`orion-session-badge orion-session-${mode || "unknown"}`}>{icon}{label}</span>;
}

export function PremarketResearchStrip({ research, onAnalyze }) {
  const items = Array.isArray(research?.items) ? research.items : [];
  if (!items.length) return null;
  return (
    <section className="premarket-research-strip" aria-label="Premarket Orion research">
      <div className="premarket-research-strip-heading">
        <div><span className="core-eyebrow">PRE-MARKET ORION</span><strong>Premarket research candidates</strong></div>
        <small>Opening confirmation required</small>
      </div>
      <div className="premarket-research-strip-items">
        {items.slice(0, 5).map((item) => {
          const ticker = item?.ticker || item?.symbol;
          const pmScore = item?.premarket_score ?? item?.analysis?.score ?? item?.score ?? null;
          const direction = item?.opening_outlook ?? item?.direction ?? item?.analysis?.direction ?? "neutral";
          return (
            <button type="button" key={ticker} className="premarket-research-chip" onClick={() => ticker && onAnalyze?.(ticker)} disabled={!ticker}>
              <span><strong>{ticker || "N/A"}</strong><small>{String(direction).toUpperCase()}</small></span>
              <span><b>{score(pmScore)}</b><small>PM score</small></span>
              <span><b>{item?.directional_conviction != null ? `${Math.round(item.directional_conviction)}/100` : "Research"}</b><small>Conviction</small></span>
              <ArrowRight size={13} />
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ClosedMetrics({ analysis, afterHours = false }) {
  const price = finite(analysis?.price) ?? finite(analysis?.reference_price) ?? finite(analysis?.quote?.price) ?? finite(analysis?.evidence?.quote?.price);
  const lastScore = finite(analysis?.last_regular_orion_score) ?? finite(analysis?.orion_score) ?? finite(analysis?.score);
  return (
    <div className="orion-session-metrics orion-session-metrics-closed">
      <div className="orion-session-message"><Clock3 size={18} /><div><strong>{afterHours ? "After-hours research mode" : "Market is closed"}</strong><p>Live regular-session scoring is paused. Orion can still summarize company, news, chart and latest completed-session context.</p></div></div>
      <div className="orion-mini-metric-grid">
        <div><small>Latest price</small><strong>{price === null ? "N/A" : `$${price.toFixed(2)}`}</strong></div>
        <div><small>Last regular score</small><strong>{lastScore === null ? "N/A" : `${Math.round(lastScore)} / 100`}</strong></div>
      </div>
    </div>
  );
}

function premarketState(analysis, predictive, open5m) {
  const premarket = analysis?.premarket || {};
  const fullHistory = analysis?.full_intraday_history === true || premarket?.full_intraday_history === true;
  const pointSnapshot = analysis?.status === "limited_point_snapshot" || premarket?.analysis_status === "limited_point_snapshot";
  const reason = predictive?.reason || open5m?.reason || "";

  if (open5m && predictive?.available === true) {
    return open5m?.actionable === true ? "VALIDATED SIGNAL" : "BELOW VALIDATED GATE";
  }
  if (reason === "trained_hierarchical_model_artifact_missing") return "MODEL NOT LOADED";
  if (reason === "sip_prediction_history_unavailable" || reason === "usable_sip_minute_history_required" || reason === "full_sip_minute_history_required") {
    return fullHistory ? "AWAITING SIP PREDICTION DATA" : "WAITING FOR USABLE PREMARKET DATA";
  }
  if (reason === "training_feed_mismatch_requires_sip") return "SIP PREDICTION DATA REQUIRED";
  if (pointSnapshot) return "LIMITED PREMARKET DATA";
  if (fullHistory) return "PREMARKET DATA ACTIVE";
  return "WAITING FOR USABLE PREMARKET DATA";
}

function PremarketMetrics({ analysis }) {
  const premarket = analysis?.premarket || {};
  const pmScore = analysis?.premarket_score ?? premarket?.premarket_score ?? premarket?.analysis?.score ?? analysis?.analysis?.score ?? analysis?.orion_score ?? null;
  const outlook = analysis?.opening_outlook || premarket?.opening_outlook || (analysis?.direction === "bullish" ? "UP BIAS" : analysis?.direction === "bearish" ? "DOWN BIAS" : "WAIT");
  const conviction = finite(analysis?.directional_conviction ?? premarket?.directional_conviction);
  const predictive = analysis?.predictive_outlook || premarket?.predictive_outlook || {};
  const open5m = predictive?.signals?.open_5m || null;
  const forecastAvailable = analysis?.forecast_available === true || premarket?.forecast_available === true || (predictive?.available === true && Boolean(open5m));
  const horizon = analysis?.forecast_horizon || premarket?.forecast_horizon || (open5m ? "OPEN -> FIRST 5 MIN" : null);
  const pmPrice = finite(analysis?.premarket_price) ?? finite(premarket?.premarket_price) ?? finite(analysis?.analysis?.premarket_price);
  const actionable = open5m?.actionable === true;
  const direction = actionable ? String(open5m?.direction || "NO_EDGE").toUpperCase() : "NO EDGE";
  const state = premarketState(analysis, predictive, open5m);
  const hasPremarketContext = pmScore !== null || pmPrice !== null || analysis?.full_intraday_history === true || premarket?.full_intraday_history === true;
  const outlookLabel = forecastAvailable ? outlook : hasPremarketContext ? "OBSERVING" : "INSUFFICIENT DATA";
  const horizonLabel = forecastAvailable ? (horizon || "OPEN -> FIRST 5 MIN") : hasPremarketContext ? "VALIDATED MODEL PENDING" : "WAIT FOR DATA";

  return (
    <div className="orion-session-metrics orion-session-metrics-premarket">
      <div className="orion-premarket-score">
        <div className="orion-score-ring" style={scoreRingStyle(pmScore)}><div><strong>{score(pmScore)}</strong><span>/100</span></div></div>
        <div><small>Premarket Orion Score</small><strong>{forecastAvailable ? outlook : hasPremarketContext ? "OBSERVING" : "WAIT"}</strong><p>Setup quality plus directional opening outlook; not probability of profit.</p></div>
      </div>
      <div className="orion-mini-metric-grid">
        <div><small>Opening outlook</small><strong>{outlookLabel}</strong></div>
        <div><small>Directional conviction</small><strong>{conviction === null ? "N/A" : `${Math.round(conviction)} / 100`}</strong></div>
        <div><small>Forecast window</small><strong>{horizonLabel}</strong></div>
        <div><small>Premarket price</small><strong>{pmPrice === null ? "N/A" : `$${pmPrice.toFixed(2)}`}</strong></div>
      </div>
      <div className="orion-session-message"><ShieldCheck size={18} /><div><strong>Validated predictive model · Open → 5 min</strong><p>{actionable ? `${direction} signal passed the validated EDGE + DIRECTION gate.` : `No actionable model signal. ${state}.`}</p></div></div>
      <div className="orion-mini-metric-grid">
        <div><small>Model direction</small><strong>{open5m ? direction : state}</strong></div>
        <div><small>Edge probability</small><strong>{open5m ? probability(open5m.edge_probability) : "N/A"}</strong></div>
        <div><small>Direction confidence</small><strong>{open5m ? probability(open5m.direction_confidence) : "N/A"}</strong></div>
        <div><small>UP / DOWN given edge</small><strong>{open5m ? `${probability(open5m.up_given_edge)} / ${probability(open5m.down_given_edge)}` : "N/A"}</strong></div>
      </div>
      <PremarketPredictiveDiagnostics analysis={analysis} />
    </div>
  );
}

function RegularMetrics({ analysis }) {
  const orionScore = analysis?.orion_score ?? analysis?.score ?? analysis?.final_score ?? analysis?.quality_score ?? null;
  const adjusted = analysis?.adjusted_orion_score ?? analysis?.adjusted_score ?? analysis?.confidence_score ?? analysis?.confidence ?? null;
  const up = analysis?.up_probability ?? analysis?.probability_up ?? analysis?.bullish_probability ?? analysis?.long_probability ?? null;
  const down = analysis?.down_probability ?? analysis?.probability_down ?? analysis?.bearish_probability ?? analysis?.short_probability ?? null;
  const manipulation = analysis?.manipulation_risk ?? analysis?.manipulationRisk ?? analysis?.risk?.manipulation ?? null;
  return (
    <div className="orion-session-metrics">
      <div className="orion-premarket-score"><div className="orion-score-ring" style={scoreRingStyle(orionScore)}><div><strong>{score(orionScore)}</strong><span>/100</span></div></div><div><small>Orion Score</small><strong>{score(adjusted)} adjusted</strong><p>Unified regular-session research score.</p></div></div>
      <div className="orion-mini-metric-grid">
        <div><small>Up probability</small><strong>{probability(up)}</strong></div>
        <div><small>Down probability</small><strong>{probability(down)}</strong></div>
        <div><small>Manipulation risk</small><strong>{riskLabel(manipulation)}</strong></div>
        <div><small>Integrity</small><strong><ShieldCheck size={14} /> ACTIVE</strong></div>
      </div>
    </div>
  );
}

export default function SessionAwareOrionMetrics({ analysis, session, busy = false }) {
  if (busy) return <div className="orion-session-metrics"><div className="orion-session-message"><span className="core-loading-dot" /><div><strong>Orion is calculating...</strong><p>Session-aware research is running for the selected stock.</p></div></div></div>;
  const mode = String(session || analysis?.session_mode || analysis?.market_session || analysis?.session || "").toLowerCase();
  if (mode === "premarket") return <PremarketMetrics analysis={analysis || {}} />;
  if (mode === "closed") return <ClosedMetrics analysis={analysis || {}} />;
  if (mode === "after_hours") return <ClosedMetrics analysis={analysis || {}} afterHours />;
  return <RegularMetrics analysis={analysis || {}} />;
}
