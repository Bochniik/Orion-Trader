import { useEffect, useState } from "react";
import { getOurAISymbolResearch } from "../api/api";
import "./ouraiEvidence.css";

const FROZEN_SYMBOLS = new Set(["NVDA", "AAPL", "TSLA", "JPM", "AMD", "META", "MSFT"]);

// Availability diagnostics are not predictive metrics. Keep all messages
// local and fixed; never display raw upstream errors or stack traces.
const OUTAGE_DETAILS = Object.freeze({
  bridge_disabled: "Local OurAI bridge is disabled (opt-in). No evidence was requested.",
  upstream_timeout: "Local OurAI evidence request timed out. Data availability issue, not a model accuracy result.",
  upstream_connection_failure: "Could not reach the local OurAI service. Connection issue, not a model accuracy result.",
  upstream_http_failure: "Local OurAI service returned an HTTP error. No evidence was accepted.",
  invalid_upstream_evidence: "Local OurAI response failed evidence validation. Values were withheld.",
  no_symbol_observations: "The verified journal has no observations for this stock.",
  no_verified_evidence: "No verified research evidence is available for this stock.",
});


function safeCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("en-US") : "Unavailable";
}

function safeBps(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? `${value.toFixed(2)} bps`
    : "Unavailable";
}

function safeUtc(value) {
  if (typeof value !== "string") return "Unavailable";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? `${new Date(timestamp).toISOString().slice(0, 16).replace("T", " ")} UTC` : "Unavailable";
}

// Presentation-only contract: never turn a generic "available" response into
// OurAI forward evidence, and never render directional or trading fields.
export function SymbolResearchSummary({ briefing, selectedTicker }) {
  const symbol = String(selectedTicker || "").trim().toUpperCase();
  const supported = FROZEN_SYMBOLS.has(symbol);
  const verified = supported &&
    briefing?.symbol === symbol &&
    briefing?.mode === "RESEARCH_SHADOW_ONLY" &&
    briefing?.trading_enabled === false &&
    briefing?.decision === null &&
    briefing?.p_up === null &&
    briefing?.p_down === null &&
    briefing?.signed_return_percent === null &&
    briefing?.magnitude_status === "verified_forward" &&
    briefing?.magnitude?.source === "ourai_verified_forward_journal" &&
    briefing?.magnitude?.kind === "absolute_magnitude_only" &&
    briefing?.magnitude?.horizon_minutes === 15 &&
    briefing?.magnitude?.direction_available === false;
  const magnitude = verified ? briefing.magnitude : null;
  const safeUnavailableReason = (
    briefing?.symbol === symbol &&
    briefing?.mode === "RESEARCH_SHADOW_ONLY" &&
    briefing?.trading_enabled === false &&
    briefing?.magnitude_status === "unavailable" &&
    typeof briefing?.magnitude_unavailable_reason === "string" &&
    Object.prototype.hasOwnProperty.call(OUTAGE_DETAILS, briefing.magnitude_unavailable_reason)
  ) ? OUTAGE_DETAILS[briefing.magnitude_unavailable_reason] : null;

  return (
    <section className="ourai-evidence intelligence-module" aria-label="OurAI per-symbol research">
      <header className="ourai-evidence-heading">
        <div>
          <p className="core-eyebrow">OURAI · PER-SYMBOL RESEARCH</p>
          <h2>{supported ? symbol : "Choose a supported stock"} · 15-minute absolute movement</h2>
          <p>Separate read-only research context. It never changes Orion decisions.</p>
        </div>
        <span className={`ourai-evidence-status ${verified ? "available" : "unavailable"}`}>
          {verified ? "Verified forward journal" : "No verified symbol evidence"}
        </span>
      </header>
      {!supported ? (
        <div className="ourai-evidence-empty" role="status">
          <strong>Select NVDA, AAPL, TSLA, JPM, AMD, META or MSFT</strong>
          <p>Only the frozen V3 research universe has this evidence contract.</p>
        </div>
      ) : !verified ? (
        <div className="ourai-evidence-empty" role="status">
          <strong>Verified {symbol} magnitude evidence unavailable</strong>
          <p>{safeUnavailableReason || "The bridge may be disabled, disconnected or missing this stock. No estimated values are substituted."}</p>
        </div>
      ) : (
        <>
          <div className="ourai-evidence-stats">
            <div className="ourai-metric"><span>Resolved observations</span><strong>{safeCount(magnitude.resolved)}</strong><small>Verified local journal</small></div>
            <div className="ourai-metric"><span>Pending observations</span><strong>{safeCount(magnitude.pending)}</strong><small>Not yet scored</small></div>
            <div className="ourai-metric"><span>V3 absolute-move MAE</span><strong>{safeBps(magnitude.champion_mae_bps)}</strong><small>Historical forward error</small></div>
            <div className="ourai-metric"><span>Latest expected absolute move</span><strong>{safeBps(magnitude.latest_expected_magnitude_bps)}</strong><small>No UP/DOWN information</small></div>
          </div>
          <p className="ourai-evidence-provenance">
            Snapshot evaluated {safeUtc(magnitude.as_of)}. These observations are not a live trading signal or independent proof of profitability.
          </p>
        </>
      )}
      <p className="ourai-evidence-warning">
        Direction P(UP)/P(DOWN), signed return (%) and trade decision: <b>unavailable / not independently validated</b>.
        Article-grounded news interpretation is not provided by this endpoint.
      </p>
    </section>
  );
}

export default function OurAISymbolResearchPanel({ selectedTicker }) {
  const symbol = String(selectedTicker || "").trim().toUpperCase();
  const [briefing, setBriefing] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!FROZEN_SYMBOLS.has(symbol)) {
      setBriefing(null);
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setBriefing(null);
    setLoading(true);
    getOurAISymbolResearch(symbol, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setBriefing(data); })
      .catch(() => { if (!controller.signal.aborted) setBriefing(null); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [symbol]);

  if (!FROZEN_SYMBOLS.has(symbol)) return <SymbolResearchSummary selectedTicker={symbol} briefing={null} />;
  if (loading) {
    return <div className="ourai-evidence-loading" role="status">Loading {symbol} research evidence…</div>;
  }
  return <SymbolResearchSummary selectedTicker={symbol} briefing={briefing} />;
}
