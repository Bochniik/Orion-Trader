import { useEffect, useState } from "react";
import { CalendarClock, Network } from "lucide-react";
import { getTickerEarningsPack, getTickerRelationships } from "../api/api";

export default function RelationshipEarningsPanels({ ticker }) {
  const [relationships, setRelationships] = useState(null);
  const [earnings, setEarnings] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRelationships(null); setEarnings(null); setError("");
    if (!ticker) return;
    let live = true;
    Promise.all([getTickerRelationships(ticker), getTickerEarningsPack(ticker)])
      .then(([r,e]) => { if (live) { setRelationships(r); setEarnings(e); } })
      .catch((err) => live && setError(err?.message || "Relationship or earnings context unavailable."));
    return () => { live = false; };
  }, [ticker]);

  if (!ticker) return null;
  const edges = relationships?.edges || [];
  const reactions = earnings?.historical_reactions || [];

  return <div className="ticker-intelligence-grid">
    <section className="intelligence-module">
      <header className="intelligence-module-header"><div><p className="core-eyebrow">RELATIONSHIP GRAPH</p><h2><Network size={17}/> {ticker} market context</h2><p>Classification and statistically observed relationships only.</p></div></header>
      {error && <p className="core-warning">{error}</p>}
      <div className="relationship-nodes">
        {(relationships?.nodes || []).map((node)=><span key={node.id} className={"relationship-node "+node.kind}><b>{node.label}</b><small>{node.kind.replaceAll("_"," ")}</small></span>)}
      </div>
      <div className="relationship-edges">
        {edges.map((edge,index)=><div key={index}><span>{edge.from} → {edge.to}</span><strong>{edge.kind === "historical_correlation" ? (edge.status === "available" ? "corr "+edge.value : "Insufficient evidence") : edge.kind.replaceAll("_"," ")}</strong>{edge.sample_size != null && <small>n={edge.sample_size}</small>}</div>)}
      </div>
      <p className="sizing-semantics">{relationships?.move_classification?.reason || "Move classification unavailable."}</p>
    </section>

    <section className="intelligence-module">
      <header className="intelligence-module-header"><div><p className="core-eyebrow">EARNINGS PACK</p><h2><CalendarClock size={17}/> {ticker} {earnings?.mode === "reaction_analysis" ? "reaction analysis" : "preparation"}</h2><p>Provider-backed expectations and historical reactions; no invented consensus.</p></div></header>
      <div className="earnings-summary">
        <div><span>Earnings date</span><strong>{earnings?.earnings_date || "Unavailable"}</strong></div>
        <div><span>Typical abs. gap</span><strong>{earnings?.typical_gap_behaviour?.status === "available" ? earnings.typical_gap_behaviour.value_percent+"%" : "Insufficient evidence"}</strong><small>n={earnings?.typical_gap_behaviour?.sample_size ?? 0}</small></div>
        <div><span>60d annualized vol</span><strong>{earnings?.volatility_context?.status === "available" ? earnings.volatility_context.annualized_percent+"%" : "Insufficient evidence"}</strong><small>n={earnings?.volatility_context?.sample_size ?? 0}</small></div>
      </div>
      <div className="earnings-expectations">
        <strong>Available expectations</strong>
        {Object.keys(earnings?.expectations || {}).length ? Object.entries(earnings.expectations).map(([k,v])=><span key={k}>{k}: <b>{String(v)}</b></span>) : <span>Unavailable from provider.</span>}
      </div>
      {earnings?.scenarios && <div className="earnings-scenarios">{["bull","base","bear"].map((key)=><div key={key}><b>{key}</b><span>{earnings.scenarios[key]}</span></div>)}</div>}
      {reactions.length > 0 && <details><summary>Historical post-earnings reactions</summary><div className="earnings-reactions">{reactions.slice(-6).map((row)=><span key={row.earnings_date}><b>{row.earnings_date?.slice(0,10)}</b> gap {row.gap_percent ?? "N/A"}% · session {row.session_reaction_percent ?? "N/A"}%</span>)}</div></details>}
      <p className="sizing-semantics">{earnings?.semantics}</p>
    </section>
  </div>;
}
