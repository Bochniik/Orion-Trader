import { lazy, Suspense, useEffect, useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { checkAlerts, getAlerts, getPortfolio } from "../api/api";
import Watchlist from "../components/Watchlist";
import useAsyncTask from "./useAsyncTask";
import { localTime } from "./decisionPresentation";
import SavedPlans from "./SavedPlans";
import DecisionQuality from "./DecisionQuality";

const PortfolioPanel = lazy(() => import("../components/PortfolioPanel"));

export default function MyStocksView({ saved, savedError, savedLoading, onSave, onRemove, onAnalyze, dataRevision }) {
  const [ticker, setTicker] = useState("");
  const [inputError, setInputError] = useState("");
  const [savingTicker, setSavingTicker] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const portfolio = useAsyncTask(), alerts = useAsyncTask();
  const refresh = () => { portfolio.run(() => getPortfolio()); alerts.run(() => getAlerts()); };
  useEffect(() => { refresh(); }, [dataRevision]);
  async function add(event) {
    event.preventDefault();
    const symbol = ticker.trim().toUpperCase();
    if (!/^[A-Z0-9.^=-]{1,15}$/.test(symbol)) { setInputError("Enter a valid ticker."); return; }
    if (saved.some(item => String(item?.ticker || item || "").trim().toUpperCase() === symbol)) {
      setInputError(`${symbol} is already in your watchlist.`);
      return;
    }
    setInputError("");
    setSavingTicker(true);
    try {
      if (await onSave(symbol)) setTicker("");
    } finally {
      setSavingTicker(false);
    }
  }
  const normalizedTicker = ticker.trim().toUpperCase();
  const duplicateTicker = normalizedTicker && saved.some(item => String(item?.ticker || item || "").trim().toUpperCase() === normalizedTicker);
  const rules = (alerts.data?.alerts || []).filter(rule => rule.enabled);
  const exceptions = rules.filter(rule => rule.triggered || rule.message?.startsWith("Check failed"));
  const positions = Object.entries(portfolio.data?.positions || {});
  return <section className="core-view">
    <div className="core-page-heading"><div><p className="core-eyebrow">KEEP WHAT MATTERS CLOSE</p><h1>My Stocks</h1><p>Your watchlist and positions, without the noise.</p></div>
      <button type="button" className="core-button secondary" onClick={refresh} disabled={portfolio.busy || alerts.busy}><RefreshCw size={16} />Refresh</button></div>
    <section className="core-stocks-status" aria-label="My Stocks overview">
      <div><span>Saved</span><strong>{savedLoading ? "—" : saved.length}</strong><small>Watchlist tickers</small></div>
      <div><span>Active checks</span><strong>{alerts.busy && !alerts.data ? "—" : rules.length}</strong><small>Enabled alerts</small></div>
      <div className={exceptions.length ? "has-attention" : ""}><span>Needs attention</span><strong>{alerts.busy && !alerts.data ? "—" : exceptions.length}</strong><small>Triggered or failed</small></div>
      <div><span>Positions</span><strong>{portfolio.busy && !portfolio.data ? "—" : positions.length}</strong><small>{portfolio.data?.source_label || "Account snapshot"}</small></div>
    </section>
    <section className="core-monitoring" aria-label="Monitoring status"><h2>What needs attention</h2>
      {alerts.busy ? <p role="status">Loading saved checks…</p> : alerts.error ? <p role="alert">Saved checks unavailable: {alerts.error}</p>
        : exceptions.length ? <ul>{exceptions.map(rule => <li key={rule.id}><button className="core-text-button" type="button" onClick={() => onAnalyze(rule.ticker)}>{rule.ticker}</button><span>{rule.message}</span><small>Last checked: {localTime(rule.last_checked_at?.includes("T") ? rule.last_checked_at : rule.last_checked_at ? `${rule.last_checked_at.replace(" ", "T")}Z` : null)}</small></li>)}</ul>
        : <p>{!rules.length ? "No active monitoring rules. Saved stocks are not automatically monitored yet." : rules.some(rule => !rule.last_checked_at) ? "Some saved rules have not been checked yet." : "No exceptions in the last saved alert checks."}</p>}
      {rules.length > 0 && <><button className="core-text-button" type="button" disabled={alerts.busy} onClick={() => alerts.run(() => checkAlerts())}>Check saved alerts now</button><p className="core-muted">Checks run only on request. Previous checks do not establish that a thesis is still valid.</p></>}
    </section>
    <SavedPlans onAnalyze={onAnalyze} dataRevision={dataRevision} />
    <DecisionQuality dataRevision={dataRevision} />
    <form className={`core-save-form${duplicateTicker ? " is-duplicate" : ""}${savingTicker ? " is-saving" : ""}`} onSubmit={add} aria-busy={savingTicker}>
      <div className="core-save-copy"><label htmlFor="save-ticker">Save a stock</label><small>Add a ticker to your market watchlist.</small></div>
      <div className="core-save-command"><span aria-hidden="true">›</span><input id="save-ticker" placeholder="AAPL" value={ticker} maxLength={15} autoComplete="off" spellCheck="false" disabled={savingTicker} onChange={event => { setTicker(event.target.value.toUpperCase()); if (inputError) setInputError(""); }} /></div>
      <button className="core-button secondary" type="submit" disabled={!normalizedTicker || duplicateTicker || savingTicker}><Plus size={16} />{savingTicker ? "Saving…" : duplicateTicker ? "Saved" : "Add"}</button>
      <span className="core-save-hint" aria-live="polite">{duplicateTicker ? `${normalizedTicker} is already saved` : normalizedTicker ? `Ready to add ${normalizedTicker}` : "Type a US ticker symbol"}</span>
    </form>
    {inputError && <p className="core-warning" role="alert">{inputError}</p>}
    {savedError ? <p className="core-error" role="alert">{savedError}</p> : savedLoading ? <p role="status">Loading watchlist…</p>
      : saved.length ? <Watchlist watchlist={saved} onSelectStock={onAnalyze} onRemoveStock={onRemove} /> : <p className="core-quiet">Your watchlist is empty. Save a ticker here or from an analysis.</p>}
    <section className="core-positions"><div className="core-section-label"><h2>Positions</h2><span>{portfolio.data?.source_label || "Account snapshot"}</span></div>
      {portfolio.busy ? <p role="status">Loading positions…</p> : portfolio.error ? <p role="alert">{portfolio.error}</p> : positions.length ? <div className="core-position-list">{positions.map(([symbol, row]) => <button key={symbol} type="button" onClick={() => onAnalyze(row.ticker || symbol)}><strong>{row.ticker || symbol}</strong><span>{row.quantity} shares</span><span>Analyze →</span></button>)}</div> : <p className="core-quiet">No positions in the selected account.</p>}
      {portfolio.data && <details className="core-portfolio-details" open={detailsOpen} onToggle={event => setDetailsOpen(event.currentTarget.open)}><summary>Account details and existing journal</summary>{detailsOpen && <Suspense fallback={<p>Loading account details…</p>}><PortfolioPanel portfolio={portfolio.data} onJournalSaved={() => portfolio.run(() => getPortfolio())} /></Suspense>}</details>}
    </section>
  </section>;
}
