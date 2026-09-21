import { useEffect, useState } from "react";
import { BrainCircuit, History } from "lucide-react";
import { getTickerInvestmentMemory, getTickerPersonality } from "../api/api";

function pct(value) {
  const number = Number(value);
  return Number.isFinite(number) ? (number * 100).toFixed(1) + "%" : "Insufficient evidence";
}

function metricLabel(metric, kind = "ratio") {
  if (!metric || metric.status !== "available") return "Insufficient evidence";
  return kind === "ratio" ? pct(metric.value) : String(metric.value);
}

export default function TickerIntelligencePanels({ ticker }) {
  const [personality, setPersonality] = useState(null);
  const [memory, setMemory] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setPersonality(null); setMemory(null); setError("");
    if (!ticker) return;
    let live = true;
    Promise.all([getTickerPersonality(ticker), getTickerInvestmentMemory(ticker)])
      .then(([p,m]) => { if (live) { setPersonality(p); setMemory(m); } })
      .catch((e) => { if (live) setError(e?.message || "Ticker intelligence unavailable."); });
    return () => { live = false; };
  }, [ticker]);

  if (!ticker) return null;
  const profile = personality?.empirical_profile || {};
  const events = memory?.items || [];

  return <div className="ticker-intelligence-grid">
    <section className="intelligence-module">
      <header className="intelligence-module-header">
        <div><p className="core-eyebrow">TICKER PERSONALITY</p><h2><BrainCircuit size={17}/> {ticker} empirical profile</h2><p>Only settled evidence is promoted to a metric.</p></div>
        <span className="intelligence-selected-chip">n={personality?.sample_size ?? 0}</span>
      </header>
      {error && <p className="core-warning">{error}</p>}
      <div className="personality-metrics">
        <div><span>Forecast accuracy</span><strong>{metricLabel(profile.forecast_accuracy)}</strong><small>n={profile.forecast_accuracy?.sample_size ?? 0}</small></div>
        <div><span>Positive decisions</span><strong>{metricLabel(profile.positive_decision_rate)}</strong><small>n={profile.positive_decision_rate?.sample_size ?? 0}</small></div>
        <div><span>Avg signed return</span><strong>{metricLabel(profile.average_signed_return)}</strong><small>n={profile.average_signed_return?.sample_size ?? 0}</small></div>
        <div><span>After-cost return</span><strong>{metricLabel(profile.average_after_cost_return)}</strong><small>n={profile.average_after_cost_return?.sample_size ?? 0}</small></div>
      </div>
      <div className="personality-horizons">
        <span>Strongest horizon <strong>{personality?.strongest_orion_horizon || "Insufficient evidence"}</strong></span>
        <span>Weakest horizon <strong>{personality?.weakest_orion_horizon || "Insufficient evidence"}</strong></span>
      </div>
      {personality?.lessons?.length > 0 && <ul className="personality-lessons">{personality.lessons.slice(0,3).map((x,i)=><li key={i}>{x}</li>)}</ul>}
      <details><summary>Behavioral metrics not yet validated</summary><div className="unsupported-metrics">{Object.entries(personality?.behavioral_metrics || {}).map(([key,row])=><span key={key}><b>{key.replaceAll("_"," ")}</b> — {row.label}</span>)}</div></details>
    </section>

    <section className="intelligence-module">
      <header className="intelligence-module-header">
        <div><p className="core-eyebrow">INVESTMENT MEMORY</p><h2><History size={17}/> {ticker} timeline</h2><p>Facts, model observations and Orion interpretations stay separated.</p></div>
        <span className="intelligence-selected-chip">{events.length} events</span>
      </header>
      {events.length === 0 ? <div className="intelligence-module-empty"><p>No persistent ticker history yet.</p></div> :
        <div className="ticker-memory-list">{events.slice(0,12).map((event,index)=><article key={(event.record_id ?? "x")+"-"+index}>
          <div className="ticker-memory-meta"><span>{String(event.kind || "").replaceAll("_"," ")}</span><time>{event.occurred_at || "Time unavailable"}</time></div>
          <strong>{event.title}</strong>
          <p>{typeof event.detail === "string" ? event.detail : JSON.stringify(event.detail)}</p>
          <small>{event.factual ? "FACTUAL HISTORICAL DATA" : "MODEL / ORION INTERPRETATION"} · {event.source}</small>
        </article>)}</div>
      }
      {memory?.semantics && <p className="sizing-semantics">{memory.semantics}</p>}
    </section>
  </div>;
}
