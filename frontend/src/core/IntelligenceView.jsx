import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BrainCircuit, RefreshCw, ShieldAlert } from "lucide-react";
import { getOrionIntelligenceBriefing } from "../api/api";
import PositionSizingAssistant from "./PositionSizingAssistant";
import "./intelligence.css";

function metric(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "Unavailable";
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number)}${suffix}` : String(value);
}

export default function IntelligenceView({ selectedTicker, onSelectTicker, onAnalyze }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await getOrionIntelligenceBriefing());
    } catch (err) {
      setError(err?.message || "Could not load Orion Intelligence.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const items = useMemo(() => data?.items || [], [data]);

  return (
    <div className="intelligence-page">
      <section className="intelligence-hero">
        <div>
          <p className="core-eyebrow">ORION INTELLIGENCE</p>
          <h1>{data?.title || "Orion Intelligence"}</h1>
          <p>What matters now, why it matters, and what Orion already knows.</p>
        </div>
        <button type="button" className="core-button intelligence-refresh" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> {loading ? "Refreshing" : "Refresh"}
        </button>
      </section>

      {error && <div className="core-error" role="alert">{error}</div>}

      {!error && !loading && items.length === 0 && (
        <section className="intelligence-empty">
          <BrainCircuit size={34} strokeWidth={1.4} />
          <h2>{data?.mode === "next_session" ? "No next-session candidates yet" : "No briefing candidates yet"}</h2>
          <p>{data?.message || "Orion has not published enough evidence for a prioritized briefing."}</p>
        </section>
      )}

      {items.length > 0 && (
        <div className="intelligence-grid">
          {items.map((item) => (
            <article className={`intelligence-card ${selectedTicker === item.ticker ? "selected" : ""}`} key={`${item.ticker}-${item.expected_horizon}`}>
              <header>
                <div>
                  <span className="intelligence-ticker">{item.ticker}</span>
                  <span className="intelligence-state">{item.setup_state || "research"}</span>
                </div>
                <strong>{item.directional_bias || "Neutral / unavailable"}</strong>
              </header>
              <div className="intelligence-metrics">
                <div><span>Confidence</span><strong>{metric(item.confidence, "%")}</strong></div>
                <div><span>Setup quality</span><strong>{metric(item.setup_quality)}</strong></div>
                <div><span>Liquidity</span><strong>{metric(item.liquidity_score)}</strong></div>
                <div><span>Horizon</span><strong>{item.expected_horizon || "Unavailable"}</strong></div>
              </div>
              <div className="intelligence-evidence">
                <p><b>Why it is here:</b> {item.main_reason || "No explanatory evidence was published."}</p>
                <p><b>Catalyst:</b> {item.catalyst || "No verified catalyst attached."}</p>
                <p className="intelligence-risk"><ShieldAlert size={13} /> {item.main_risk || "No explicit risk note published."}</p>
              </div>
              <div className="intelligence-card-actions">
                <button type="button" className="intelligence-select" onClick={() => onSelectTicker?.(item.ticker)}>
                  {selectedTicker === item.ticker ? "Selected in Intelligence" : "Use in Intelligence"}
                </button>
                <button type="button" className="intelligence-open" onClick={() => onAnalyze?.(item.ticker)}>
                  Open full analysis <ArrowRight size={14} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      <PositionSizingAssistant ticker={selectedTicker} />

      {data?.ranking_semantics && (
        <details className="intelligence-provenance">
          <summary>How this briefing is built</summary>
          <p>{data.ranking_semantics}</p>
          <small>Source: {data.source}. Missing values remain unavailable.</small>
        </details>
      )}
    </div>
  );
}
