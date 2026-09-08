import { useState } from "react";
import { getResearchSetupHistory, getResearchSetupAnalytics, explainResearchSetup } from "../api/api";
import { localTime } from "./decisionPresentation";

const price = value => typeof value === "number" && Number.isFinite(value) ? `$${value.toFixed(2)}` : "Unavailable";
const percent = value => typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "Not measured";

export function ResearchSetupCard({ row, onAnalyze, onExplain, now = Date.now(), error }) {
  const stamp = Date.parse(row.data_timestamp);
  const stale = error || !Number.isFinite(stamp) || now - stamp > 120000 || stamp > now || row.freshness === "stale";
  return <article className="scanner-candidate-card">
    <div className="market-card-heading"><button type="button" className="market-ticker" onClick={() => onAnalyze(row.ticker)}>{row.ticker}</button><strong>{price(row.current_price)}</strong><span>{stale ? "STALE" : "DELAYED"}</span></div>
    <h3>{row.direction.toUpperCase()} · {row.strategy.replaceAll("_", " ")}</h3>
    <p>Setup quality {row.quality_score.toFixed(1)} / 100 · not a probability</p>
    <p>{typeof row.confidence === "number" ? `Model direction: ${row.confidence.toFixed(1)}% over ${row.confidence_horizon} · experimental, not trade success` : "Model probability unavailable — no compatible validated estimate."}</p>
    <p>Entry {price(row.entry_zone[0])}–{price(row.entry_zone[1])} · Stop / invalidation {price(row.stop_loss)}</p>
    <p>Target 1 {price(row.target_1)} · Target 2 {price(row.target_2)} · R/R {row.risk_reward.toFixed(2)} · after estimated costs {row.risk_reward_after_costs.toFixed(2)}</p>
    <p>Hold {row.holding_horizon.value} {row.holding_horizon.unit} · {row.market_regime.replaceAll("_", " ")}</p>
    <p className="core-muted">Liquidity {row.liquidity_score}/100 · Spread {row.spread_pct}% · Quote {localTime(row.data_timestamp)} · Features {localTime(row.feature_timestamp)}</p>
    <details><summary>Evidence and limitations · NO TRADE research</summary>{row.reasons.map((reason, index) => <p key={`r${index}`}>{reason}</p>)}{row.warnings.map((warning, index) => <p key={`w${index}`}>{warning}</p>)}</details>
    {row.setup_id && onExplain && <button type="button" className="core-button secondary" onClick={() => onExplain(row.setup_id)}>Explain saved evidence</button>}
  </article>;
}

export default function ResearchSetups({ data, onAnalyze, now, error }) {
  const [horizon, setHorizon] = useState("day");
  const [history, setHistory] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  async function loadHistory() {
    setBusy(true); setFailure("");
    try {
      const [saved, stats] = await Promise.all([getResearchSetupHistory(), getResearchSetupAnalytics()]);
      setHistory(saved.items); setAnalytics(stats);
    } catch (err) { setFailure(err.message); } finally { setBusy(false); }
  }
  async function explain(id) {
    if (busy) return;
    setBusy(true); setFailure(""); setExplanation(null);
    try { setExplanation((await explainResearchSetup(id)).interpretation.explanation); }
    catch (err) { setFailure(err.message); } finally { setBusy(false); }
  }
  const rows = data?.groups?.[horizon] || [];
  const old = (data?.last_known || []).filter(row => row.horizon === horizon);
  return <section className="scanner-surface" aria-label="Research setups">
    <header className="scanner-surface-heading"><div><p className="core-eyebrow">OPPORTUNITY ENGINE</p><h2>Auditable research setups</h2></div></header>
    <nav className="market-category-selector" aria-label="Research holding horizon">{[["day", "Day Trading"], ["swing", "Swing Trading"], ["long_term", "Long-Term Investing"]].map(([key, label]) => <button type="button" key={key} aria-pressed={horizon === key} onClick={() => setHorizon(key)}>{label}</button>)}</nav>
    <p className="core-muted">Quality ranks the evidence, not certainty. Model probabilities retain their own forecast horizon. All plans are research only; no orders.</p>
    <div className="scanner-candidate-grid">{rows.map(row => <ResearchSetupCard key={row.ticker} row={row} onAnalyze={onAnalyze} onExplain={explain} now={now} error={error} />)}</div>
    {!rows.length && <p>No qualifying {horizon.replaceAll("_", " ")} setups in the evaluated sample. Missing models do not create invented probabilities.</p>}
    {!!old.length && <details><summary>Last known research plans · STALE</summary><div className="scanner-candidate-grid">{old.slice(0, 10).map(row => <ResearchSetupCard key={row.ticker} row={row} onAnalyze={onAnalyze} onExplain={explain} now={now} error />)}</div></details>}
    <details><summary>Scanner coverage and exclusions</summary><p>Analyzed symbols this page: {data?.diagnostics?.coverage?.analyzed_symbols ?? 0}; capacity excluded: {data?.diagnostics?.coverage?.capacity_excluded ?? 0}. Not a simultaneous full-market scan.</p>{data?.diagnostics?.errors?.map((message, i) => <p key={i}>{message}</p>)}{data?.diagnostics?.rejections?.slice(0, 12).map((r, i) => <p key={i}>{r.ticker} · {r.horizon}: {r.reasons?.join(", ")}</p>)}</details>
    <button type="button" className="core-button secondary" disabled={busy} onClick={loadHistory}>{busy ? "Loading…" : "Load outcome history"}</button>
    {failure && <p className="core-error" role="alert">{failure}</p>}
    {explanation && <div><p>{explanation.summary}</p><p>{explanation.market_context}</p>{explanation.risk_considerations.map((risk, i) => <p key={i}>{risk}</p>)}</div>}
    {analytics && <div><p>Evaluated simulations: {analytics.overall.samples} · Win rate {percent(analytics.overall.win_rate)} · Expectancy {analytics.overall.expectancy_r == null ? "Not measured" : `${analytics.overall.expectancy_r.toFixed(2)}R`} · Pending {analytics.pending}</p><p className="core-muted">{analytics.semantics} {analytics.calibration.reason}</p></div>}
    {history && <details open><summary>Saved plans and outcomes ({history.length})</summary>{history.slice(0, 30).map(row => <p key={row.setup_id}>{row.ticker} · {row.horizon} · {new Date(row.created_at).toLocaleString()} · Entry {price(row.reference_entry)} · {row.outcome?.status || "pending"}{row.outcome?.status === "settled" ? ` · ${row.outcome.exit_reason} · ${row.outcome.net_r.toFixed(2)}R · MFE ${percent(row.outcome.mfe)} · MAE ${percent(row.outcome.mae)}` : ` · ${row.pending_reason || row.outcome?.reason || "Awaiting future observations"}`}</p>)}</details>}
  </section>;
}
