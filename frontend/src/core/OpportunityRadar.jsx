const CATEGORIES = [
  ["biggest_gainers", "Biggest gainers", "change_percent", "%"],
  ["biggest_losers", "Biggest losers", "change_percent", "%"],
  ["most_active", "Most active", "current_dollar_volume", ""],
  ["unusual_volume", "Unusual volume", "relative_volume", "× RVOL"],
  ["buy_pressure", "Buy pressure", "quote_imbalance", " inferred"],
  ["sell_pressure", "Sell pressure", "quote_imbalance", " inferred"],
  ["momentum_leaders", "Momentum leaders", "opportunity_score", " score"],
  ["potential_bargains", "Potential bargains", "opportunity_score", " score"],
  ["breakout_watch", "Breakout watch", "opportunity_score", " score"],
];

function value(row, field, suffix) {
  const raw = row?.[field];
  if (raw == null) return "—";
  if (field === "current_dollar_volume") return `$${(Number(raw) / 1e6).toFixed(1)}M`;
  if (field === "quote_imbalance") return `${raw > 0 ? "+" : ""}${(Number(raw) * 100).toFixed(1)}%${suffix}`;
  return `${Number(raw).toFixed(field === "relative_volume" ? 2 : 1)}${suffix}`;
}

export default function OpportunityRadar({ radar, prime = [], onAnalyze, soundAlerts = false, onSoundAlertsChange }) {
  if (!radar || !Object.keys(radar).length) return null;
  const activeBuckets = CATEGORIES.reduce((count, [id]) => count + ((radar[id] || []).length > 0 ? 1 : 0), 0);
  const surfacedRows = CATEGORIES.reduce((count, [id]) => count + Math.min((radar[id] || []).length, 5), 0);
  return <section className="core-radar" aria-label="Opportunity Radar">
    <div className="core-section-label"><div><h2>Opportunity Radar</h2><p>Current discovery buckets from the fetched market universe.</p></div><div className="core-radar-heading-actions"><label className="core-auto-refresh"><input type="checkbox" checked={soundAlerts} onChange={event => onSoundAlertsChange?.(event.target.checked)} />Sound alerts</label><span>{activeBuckets}/{CATEGORIES.length} active</span><span>{surfacedRows} signals</span><span>Liquidity-ranked evidence</span></div></div>
    {prime.length > 0 && <section className="core-prime" aria-label="Orion Prime"><div><strong>ORION PRIME</strong><span>Exceptional setup detected · {prime[0].ticker} · {prime[0].direction} · {prime[0].directional_confidence}% directional probability</span></div><button type="button" className="core-button" onClick={() => onAnalyze(prime[0].ticker)}>Review</button><small>Requires Tier A liquidity, strong model agreement, supportive regime, positive post-cost edge and no blockers. Alerts are cooldown-protected.</small></section>}
    <div className="core-radar-grid">{CATEGORIES.map(([id, title, field, suffix]) => {
      const rows = radar[id] || [];
      return <details key={id} className="core-radar-card" open={id === "biggest_gainers" || id === "most_active"}><summary><strong>{title}</strong><span>{rows.length}</span></summary>{rows.length ? <ul>{rows.slice(0, 5).map(row => <li key={`${id}-${row.ticker}`}><button type="button" className="core-text-button" onClick={() => onAnalyze(row.ticker)}>{row.ticker}</button><span>{value(row, field, suffix)}</span><small>Tier {row.liquidity_tier || "—"} · {row.liquidity_score ?? "—"}/100</small></li>)}</ul> : <p>No current evidence.</p>}</details>;
    })}</div>
    <p className="core-muted">{radar.semantics}</p>
  </section>;
}
