import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BrainCircuit, RefreshCw, ShieldAlert, Sparkles } from "lucide-react";
import { getOrionIntelligenceBriefing } from "../api/api";
import PositionSizingAssistant from "./PositionSizingAssistant";
import TickerIntelligencePanels from "./TickerIntelligencePanels";
import RelationshipEarningsPanels from "./RelationshipEarningsPanels";
import "./intelligence.css";

function displayValue(value, fallback = "Unavailable") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "object") {
    if ("value" in value) {
      const unit = value.unit ? ` ${value.unit}` : "";
      return `${value.value ?? fallback}${unit}`;
    }
    return fallback;
  }
  return String(value);
}

function metric(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "Unavailable";
  if (typeof value === "object") return displayValue(value);
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number)}${suffix}` : String(value);
}

function directionTone(value) {
  const normalized = String(displayValue(value, "")).toLowerCase();
  if (normalized.includes("bull") || normalized === "up") return "bullish";
  if (normalized.includes("bear") || normalized === "down") return "bearish";
  return "neutral";
}

function PriorityCard({ item, selected, onSelect, onAnalyze }) {
  const tone = directionTone(item.directional_bias);
  return <article className={`intelligence-priority-card ${selected ? "selected" : ""}`}>
    <header>
      <div className="intelligence-priority-identity">
        <strong>{item.ticker}</strong>
        <span>{displayValue(item.setup_state, "research")}</span>
      </div>
      <span className={`intelligence-direction ${tone}`}>{displayValue(item.directional_bias, "Unavailable")}</span>
    </header>
    <div className="intelligence-priority-metrics">
      <div><span>Setup quality</span><strong>{metric(item.setup_quality)}</strong></div>
      <div><span>Liquidity</span><strong>{metric(item.liquidity_score)}</strong></div>
      <div><span>Horizon</span><strong>{displayValue(item.expected_horizon)}</strong></div>
      <div><span>Confidence</span><strong>{metric(item.confidence, "%")}</strong></div>
    </div>
    <div className="intelligence-priority-story">
      <div><b>Why Orion cares</b><p>{displayValue(item.main_reason, "No explanatory evidence was published.")}</p></div>
      <div><b><ShieldAlert size={12}/> Key risk</b><p>{displayValue(item.main_risk, "No explicit risk note published.")}</p></div>
    </div>
    <div className="intelligence-priority-actions">
      <button type="button" onClick={() => onSelect?.(item.ticker)}>{selected ? "Selected" : "Use in Intelligence"}</button>
      <button type="button" onClick={() => onAnalyze?.(item.ticker)}>Open full analysis <ArrowRight size={13}/></button>
    </div>
  </article>;
}

function CompactCandidate({ item, selected, onSelect }) {
  const tone = directionTone(item.directional_bias);
  return <button type="button" className={`intelligence-compact-candidate ${selected ? "selected" : ""}`} onClick={() => onSelect?.(item.ticker)}>
    <span className="intelligence-compact-symbol"><strong>{item.ticker}</strong><small>{displayValue(item.setup_state, "research")}</small></span>
    <span className={`intelligence-direction ${tone}`}>{displayValue(item.directional_bias, "Unavailable")}</span>
    <span>Setup <b>{metric(item.setup_quality)}</b></span>
    <span>Liquidity <b>{metric(item.liquidity_score)}</b></span>
    <ArrowRight size={13}/>
  </button>;
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
  const priority = useMemo(() => items.slice(0, 3), [items]);
  const secondary = useMemo(() => items.slice(3), [items]);
  const selected = useMemo(
    () => items.find((item) => item.ticker === selectedTicker) || null,
    [items, selectedTicker],
  );

  useEffect(() => {
    if (!selectedTicker && items.length > 0) onSelectTicker?.(items[0].ticker);
  }, [items, selectedTicker, onSelectTicker]);

  return <div className="intelligence-page intelligence-cockpit">
    <section className="intelligence-hero">
      <div>
        <p className="core-eyebrow">ORION INTELLIGENCE</p>
        <h1>{data?.title || "Orion Intelligence"}</h1>
        <p>What matters now, why it matters, and what Orion already knows.</p>
      </div>
      <div className="intelligence-hero-actions">
        <div className="intelligence-session-state">
          <span className="intelligence-session-dot"/>
          <div><strong>{data?.mode === "next_session" ? "NEXT SESSION PREP" : "LIVE RESEARCH"}</strong><small>{displayValue(data?.market_status, "Market status unavailable")}</small></div>
        </div>
        <button type="button" className="core-button intelligence-refresh" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> {loading ? "Refreshing" : "Refresh"}
        </button>
      </div>
    </section>

    {error && <div className="core-error" role="alert">{error}</div>}

    {!error && !loading && items.length === 0 && <section className="intelligence-empty">
      <BrainCircuit size={34} strokeWidth={1.4}/>
      <h2>{data?.mode === "next_session" ? "No next-session candidates yet" : "No briefing candidates yet"}</h2>
      <p>{data?.message || "Orion has not published enough evidence for a prioritized briefing."}</p>
    </section>}

    {priority.length > 0 && <section className="intelligence-briefing-section">
      <div className="intelligence-section-label">
        <Sparkles size={14}/>
        <div><strong>TOP PRIORITY</strong><small>Highest-priority candidates from Orion's existing scanner ranking.</small></div>
      </div>
      <div className="intelligence-priority-grid">
        {priority.map((item) => <PriorityCard key={`${item.ticker}-${item.expected_horizon}`} item={item} selected={selectedTicker === item.ticker} onSelect={onSelectTicker} onAnalyze={onAnalyze}/>)}
      </div>
    </section>}

    {secondary.length > 0 && <section className="intelligence-secondary-section">
      <div className="intelligence-section-label compact">
        <div><strong>OTHER CANDIDATES</strong><small>Additional opportunities from the same briefing.</small></div>
      </div>
      <div className="intelligence-secondary-grid">
        {secondary.map((item) => <CompactCandidate key={`${item.ticker}-${item.expected_horizon}`} item={item} selected={selectedTicker === item.ticker} onSelect={onSelectTicker}/>)}
      </div>
    </section>}

    {selectedTicker && <section className="intelligence-selected-context" aria-label="Selected Intelligence Context">
      <div className="intelligence-selected-title"><span>i</span><strong>{selectedTicker}</strong><small>Selected Intelligence Context</small></div>
      <div className="intelligence-selected-facts">
        <span className={`intelligence-direction ${directionTone(selected?.directional_bias)}`}>{displayValue(selected?.directional_bias, "Direction unavailable")}</span>
        <span>Setup <b>{metric(selected?.setup_quality)}</b></span>
        <span>Liquidity <b>{metric(selected?.liquidity_score)}</b></span>
        <span>Horizon <b>{displayValue(selected?.expected_horizon)}</b></span>
      </div>
    </section>}

    <div className="intelligence-workspace">
      <div className="intelligence-workspace-main">
        <TickerIntelligencePanels ticker={selectedTicker}/>
        <RelationshipEarningsPanels ticker={selectedTicker}/>
      </div>
      <aside className="intelligence-workspace-risk">
        <PositionSizingAssistant ticker={selectedTicker}/>
      </aside>
    </div>

    {data?.ranking_semantics && <details className="intelligence-provenance">
      <summary>How this briefing is built</summary>
      <p>{displayValue(data.ranking_semantics)}</p>
      <small>Source: {displayValue(data.source)}. Missing values remain unavailable.</small>
    </details>}
  </div>;
}
