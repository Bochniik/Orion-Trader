import { localTime } from "./decisionPresentation";

export const MARKET_CATEGORIES = [
  ["orion_picks", "Orion Picks"], ["biggest_gainers", "Biggest Gainers"],
  ["biggest_losers", "Biggest Losers"], ["most_active", "Most Active"],
  ["unusual_volume", "Unusual Volume"], ["momentum_leaders", "Momentum Leaders"],
  ["potential_bargains", "Potential Bargains"], ["buy_pressure", "Buy Pressure"], ["sell_pressure", "Sell Pressure"],
];
const valid = value => typeof value === "number" && Number.isFinite(value);
const number = (value, digits = 2) => valid(value) ? value.toFixed(digits) : "Unavailable";
const percent = value => valid(value) ? `${value > 0 ? "+" : ""}${value.toFixed(2)}%` : "Unavailable";

export function MarketCategorySelector({ selected, onSelect }) {
  return <nav className="market-category-selector" aria-label="Market intelligence categories">
    {MARKET_CATEGORIES.map(([key, label]) => <button type="button" key={key} aria-pressed={selected === key} onClick={() => onSelect(key)}>{label}</button>)}
  </nav>;
}

export function observationFreshness(row, now = Date.now(), forceStale = false) {
  if (forceStale) return "stale";
  const fresh = row.freshness || {};
  if (!["current", "delayed", "stale"].includes(fresh.state)) return "unavailable";
  if (fresh.state === "stale") return "stale";
  for (const [stamp, maximum] of [[row.data_timestamp, fresh.maximum_price_age_seconds ?? 120],
    [fresh.evidence_timestamp, fresh.maximum_evidence_age_seconds ?? 120]]) {
    const parsed = Date.parse(stamp);
    if (!Number.isFinite(parsed) || parsed > now) return "unavailable";
    if ((now - parsed) / 1000 > maximum) return "stale";
  }
  return fresh.state;
}

export function categoryMetric(category, value) {
  if (!valid(value)) return "Unavailable";
  if (category === "most_active") return `$${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value)} traded`;
  if (category === "unusual_volume") return `${number(value)}× relative volume`;
  if (category === "momentum_leaders") return `${number(value, 1)} / 100 momentum`;
  if (category === "potential_bargains") return `${number(value)} ATR below VWAP`;
  if (category.endsWith("pressure")) return `${percent(value * 100)} quote imbalance`;
  return `${percent(value)} session move`;
}

export function MarketIntelligenceCard({ row, category, onAnalyze, now, forceStale }) {
  const status = observationFreshness(row, now, forceStale);
  return <article className="scanner-candidate-card market-intelligence-card">
    <div className="market-card-heading"><button type="button" className="market-ticker" onClick={() => onAnalyze(row.ticker)} aria-label={`Analyze ${row.ticker}`}>{row.ticker}</button>
      <strong>{valid(row.current_price) ? `$${number(row.current_price)}` : "Price unavailable"}</strong><span className={`scanner-status ${status}`}>{status.toUpperCase()}</span></div>
    {row.historical && <small className="core-muted">Adjusted session close · {row.session_date} · HISTORICAL</small>}
    <strong className="market-main-metric">{categoryMetric(category, row.ranking_value).replace(row.historical ? " traded" : "__unused__", " activity proxy")}</strong>
    <div className="market-card-meta"><span>Session {percent(row.change_percent)}</span><span>{row.historical ? "Partial liquidity" : "Liquidity"} {valid(row.liquidity_score) ? `${number(row.liquidity_score, 0)} / 100` : "unavailable"}</span></div>
    {row.reason && <p>{row.reason}</p>}
    <small className="core-muted">{row.provider || "Unknown source"}{row.feed ? ` · ${row.feed}` : ""} · {localTime(row.data_timestamp)}{row.feature_provider ? ` · Features: ${row.feature_provider} ${localTime(row.feature_timestamp)}` : ""}</small>
  </article>;
}

export default function MarketIntelligenceView({ data, category, error, onAnalyze, now = Date.now() }) {
  const bucket = data?.categories?.[category];
  const label = MARKET_CATEGORIES.find(([key]) => key === category)?.[1];
  const current = [], old = [];
  for (const row of bucket?.items || []) {
    (["current", "delayed"].includes(observationFreshness(row, now, Boolean(error))) ? current : old).push(row);
  }
  old.push(...(bucket?.last_known || []));
  const states = current.map(row => observationFreshness(row, now));
  const status = states.includes("delayed") ? "DELAYED" : states.length ? "CURRENT" : old.length ? "STALE" : "UNAVAILABLE";
  const coverage = data?.coverage;
  const universe = coverage?.universe;
  const historical = data?.display_mode === "historical";
  return <section className="scanner-surface" aria-label={label}>
    <header className="scanner-surface-heading"><div><p className="core-eyebrow">MARKET INTELLIGENCE</p><h2>{label}</h2></div><strong className={`scanner-status ${status.toLowerCase()}`}>{status}</strong></header>
    {category.endsWith("pressure") && <p className="core-warning"><strong>Inferred Quote Pressure</strong> · Displayed bid/ask sizes, not executed buying or selling.</p>}
    {category === "most_active" && <p>{historical ? "Completed-session dollar-activity proxy" : "Market activity by traded dollar volume"} — not “Most Bought”.</p>}
    {category === "potential_bargains" && <p>Volatility-normalized mean-reversion setups, not cheap-stock claims or validated buy signals. Missing statistical evidence excludes a stock.</p>}
    {bucket?.semantics && <p className="core-muted">{bucket.semantics}</p>}
    {data?.message && <p className="core-muted" role="status">{data.message}</p>}
    <div className="scanner-progress"><strong>PARTIAL MARKET COVERAGE</strong><span>{coverage ? `${coverage.retained_qualified_symbols ?? 0} liquidity-qualified symbols retained` : "Coverage unavailable"}</span>
      {valid(universe?.total_symbols) && <span>Rotation: {universe.rotation_complete ? universe.total_symbols : universe.next_offset ?? 0} / {universe.total_symbols} symbols</span>}
      {coverage?.last_broad_scan_at && <span>Last broad scan: {localTime(coverage.last_broad_scan_at)}</span>}</div>
    {error && <p className="core-error" role="alert">Market intelligence unavailable: {error} Cached results are STALE.</p>}
    {data?.partial_failure && <p className="core-warning">Partial provider update; coverage is incomplete.</p>}
    <div className="scanner-candidate-grid">{current.map(row => <MarketIntelligenceCard key={row.ticker} row={row} category={category} onAnalyze={onAnalyze} now={now} />)}</div>
    {!current.length && !(historical && old.length) && <p className="scanner-empty" role="status">{!data && !error ? "Loading market intelligence…" : historical ? "No qualifying evidence for this category in the completed-session sample. Daily closes cannot supply intraday setups or quote pressure." : "No fresh qualifying observations in the scanned sample."}</p>}
    {old.length > 0 && <details className="scanner-last-known" open={historical || undefined}><summary>{historical ? `Latest completed session · ${data.session_date} · HISTORICAL / STALE` : "Last known observations · STALE · not current rankings"}</summary><div className="scanner-candidate-grid">{old.map(row => <MarketIntelligenceCard key={row.ticker} row={row} category={category} onAnalyze={onAnalyze} now={now} forceStale />)}</div></details>}
    {historical && <p className="core-muted">{data.limitations} Liquidity is a partial score: no historical spread or trade-frequency evidence is invented.</p>}
    <p className="core-muted">Rankings span scanned pages, not a simultaneous full-market snapshot. Technical categories cover activity finalists; minute features may be delayed. Research only.</p>
  </section>;
}
