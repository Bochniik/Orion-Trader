import { useEffect, useMemo, useRef, useState } from "react";
import { Bell, FlaskConical, Save, Search } from "lucide-react";
import {
  checkAlerts, createAlert, deleteAlert, deleteStrategy, getAlerts,
  getStrategies, getStrategyResearch, runBacktest, runSavedStrategy, saveStrategy,
} from "../api/api";
import BacktestChart from "./BacktestChart";

const DEFAULTS = {
  sma_crossover: { fast_period: 20, slow_period: 50, allocation_percent: 100, stop_loss_percent: 0, take_profit_percent: 0 },
  rsi_reversion: { rsi_period: 14, oversold: 30, overbought: 70, allocation_percent: 100, stop_loss_percent: 0, take_profit_percent: 0 },
  breakout: { lookback: 20, allocation_percent: 100, stop_loss_percent: 0, take_profit_percent: 0 },
};

function RecordList({ rows, empty }) {
  if (!rows?.length) return <p className="muted-text">{empty}</p>;
  return <div className="research-list">{rows.slice(0, 8).map((row, index) => <div key={index}>{Object.entries(row).filter(([, value]) => value != null).slice(0, 5).map(([key, value]) => <span key={key}><strong>{key.replace(/([A-Z])/g, " $1")}:</strong> {String(value)}</span>)}</div>)}</div>;
}

export default function StrategyToolingPanel({ ticker }) {
  const [config, setConfig] = useState({ ticker, kind: "sma_crossover", period: "1y", parameters: DEFAULTS.sma_crossover, initial_cash: 10000, commission_bps: 5, slippage_bps: 5 });
  const [strategyName, setStrategyName] = useState("My strategy");
  const [strategies, setStrategies] = useState([]);
  const [result, setResult] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [alertDraft, setAlertDraft] = useState({ ticker, alert_type: "price_above", threshold: "", trade_id: "" });
  const [research, setResearch] = useState(null);
  const [loading, setLoading] = useState("");
  const [message, setMessage] = useState("");
  const notifiedAlerts = useRef(new Set());

  function applyCheckedAlerts(items) {
    setAlerts(items);
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      for (const alert of items.filter((item) => item.triggered)) {
        if (!notifiedAlerts.current.has(alert.id)) {
          new Notification(`Orion alert: ${alert.ticker}`, { body: alert.message || alert.alert_type, icon: "/orion-icon.svg" });
          notifiedAlerts.current.add(alert.id);
        }
      }
      for (const alert of items.filter((item) => !item.triggered)) notifiedAlerts.current.delete(alert.id);
    }
  }

  useEffect(() => { setConfig((current) => ({ ...current, ticker })); setAlertDraft((current) => ({ ...current, ticker })); }, [ticker]);
  async function loadStrategies() { setStrategies((await getStrategies()).strategies || []); }
  async function refreshAlerts() { setAlerts((await getAlerts()).alerts || []); }
  async function refreshResearch() { try { setResearch(await getStrategyResearch(ticker)); } catch (error) { setMessage(error.message); } }

  useEffect(() => { loadStrategies(); refreshAlerts(); }, []);
  useEffect(() => { refreshResearch(); }, [ticker]);
  useEffect(() => {
    const interval = window.setInterval(async () => { try { applyCheckedAlerts((await checkAlerts()).alerts || []); } catch { /* status remains visible */ } }, 60000);
    return () => window.clearInterval(interval);
  }, []);

  function setKind(kind) { setConfig({ ...config, kind, parameters: { ...DEFAULTS[kind] } }); }
  function setParameter(key, value) { setConfig({ ...config, parameters: { ...config.parameters, [key]: Number(value) } }); }
  const parameterLabels = useMemo(() => Object.keys(config.parameters), [config.kind]);

  async function execute(payload = config) {
    try { setLoading("backtest"); setMessage(""); setResult(await runBacktest(payload)); }
    catch (error) { setMessage(error.message); } finally { setLoading(""); }
  }
  async function saveCurrent() {
    try { setLoading("save"); await saveStrategy({ name: strategyName, ticker: config.ticker, kind: config.kind, parameters: config.parameters, period: config.period }); await loadStrategies(); setMessage("Strategy saved"); }
    catch (error) { setMessage(error.message); } finally { setLoading(""); }
  }
  async function runSaved(id) { try { setLoading(`strategy-${id}`); setResult(await runSavedStrategy(id)); } catch (error) { setMessage(error.message); } finally { setLoading(""); } }
  async function removeStrategy(id) { await deleteStrategy(id); await loadStrategies(); }

  async function addAlert(event) {
    event.preventDefault();
    try {
      const thesis = alertDraft.alert_type === "thesis_invalidation";
      await createAlert({ ticker: alertDraft.ticker, alert_type: alertDraft.alert_type, threshold: thesis ? null : Number(alertDraft.threshold), trade_id: thesis ? Number(alertDraft.trade_id) : null });
      await refreshAlerts(); setMessage("Alert saved");
    } catch (error) { setMessage(error.message); }
  }
  async function evaluateAlerts() { try { setLoading("alerts"); const data = await checkAlerts(); applyCheckedAlerts(data.alerts || []); setMessage(`${data.triggered_count} alert${data.triggered_count === 1 ? "" : "s"} triggered`); } catch (error) { setMessage(error.message); } finally { setLoading(""); } }
  async function removeAlert(id) { await deleteAlert(id); await refreshAlerts(); }

  const metrics = result?.metrics || {};
  return (
    <section className="card strategy-tooling-card">
      <div className="card-title"><FlaskConical size={20} /> Strategy tooling</div>
      {message && <p className={message.includes("saved") || message.includes("triggered") ? "success-text" : "error-text"}>{message}</p>}
      <div className="strategy-grid">
        <div className="strategy-builder"><h3>Backtest builder</h3>
          <div className="strategy-form-grid"><label>Ticker<input value={config.ticker} maxLength={15} onChange={(event) => setConfig({ ...config, ticker: event.target.value.toUpperCase() })} /></label><label>Strategy<select value={config.kind} onChange={(event) => setKind(event.target.value)}><option value="sma_crossover">SMA crossover (Golden/Death capable)</option><option value="rsi_reversion">RSI reversion</option><option value="breakout">Price breakout</option></select></label><label>History<select value={config.period} onChange={(event) => setConfig({ ...config, period: event.target.value })}><option value="6mo">6 months</option><option value="1y">1 year</option><option value="2y">2 years</option><option value="5y">5 years</option></select></label>
            {parameterLabels.map((key) => <label key={key}>{key.replaceAll("_", " ")}<input type="number" min="0" step="1" value={config.parameters[key]} onChange={(event) => setParameter(key, event.target.value)} /></label>)}
            <label>Commission bps<input type="number" min="0" value={config.commission_bps} onChange={(event) => setConfig({ ...config, commission_bps: Number(event.target.value) })} /></label><label>Slippage bps<input type="number" min="0" value={config.slippage_bps} onChange={(event) => setConfig({ ...config, slippage_bps: Number(event.target.value) })} /></label></div>
          {config.kind === "sma_crossover" && <p className="muted-text">Use fast 50 and slow 200 to test a Golden Cross entry with a later Death Cross exit. The Research workspace adds regime and entry-quality confirmation.</p>}
          <div className="strategy-actions"><button className="primary-btn" type="button" onClick={() => execute()} disabled={loading === "backtest"}>{loading === "backtest" ? "Running..." : "Run backtest"}</button><input value={strategyName} maxLength={80} onChange={(event) => setStrategyName(event.target.value)} /><button className="ghost-btn" type="button" onClick={saveCurrent}><Save size={14} /> Save</button></div>
        </div>
        <div><h3>Saved strategies</h3>{strategies.length === 0 ? <p className="muted-text">No saved strategies.</p> : <div className="saved-strategies">{strategies.map((strategy) => <div key={strategy.id}><span><strong>{strategy.name}</strong><small>{strategy.ticker} · {strategy.kind.replaceAll("_", " ")}</small></span><button type="button" onClick={() => runSaved(strategy.id)}>{loading === `strategy-${strategy.id}` ? "..." : "Run"}</button><button className="danger-btn" type="button" onClick={() => removeStrategy(strategy.id)}>Delete</button></div>)}</div>}</div>
      </div>
      {result && <div className="backtest-results"><div className="portfolio-metrics"><div><span>Total return</span><strong>{metrics.total_return_percent}%</strong></div><div><span>Buy &amp; hold</span><strong>{metrics.buy_hold_return_percent}%</strong></div><div><span>Max drawdown</span><strong>{metrics.max_drawdown_percent}%</strong></div><div><span>Win rate</span><strong>{metrics.win_rate == null ? "—" : `${metrics.win_rate}%`}</strong></div></div><p className="muted-text">Next-bar-open execution · {result.assumptions.commission_bps} bps commission · {result.assumptions.slippage_bps} bps slippage</p><BacktestChart data={result.equity_curve} /></div>}

      <div className="strategy-grid alerts-research-grid"><div><div className="section-heading"><h3><Bell size={17} /> Alerts</h3><button className="ghost-btn" type="button" onClick={evaluateAlerts}>{loading === "alerts" ? "Checking..." : "Check now"}</button></div>
        <form className="alert-form" onSubmit={addAlert}><input value={alertDraft.ticker} maxLength={15} onChange={(event) => setAlertDraft({ ...alertDraft, ticker: event.target.value.toUpperCase() })} /><select value={alertDraft.alert_type} onChange={(event) => setAlertDraft({ ...alertDraft, alert_type: event.target.value })}><option value="price_above">Price above</option><option value="price_below">Price below</option><option value="rsi_above">RSI above</option><option value="rsi_below">RSI below</option><option value="max_position_percent">Max position %</option><option value="portfolio_drawdown">Portfolio drawdown %</option><option value="thesis_invalidation">Thesis invalidation</option></select>{alertDraft.alert_type === "thesis_invalidation" ? <input type="number" min="1" placeholder="Trade ID" value={alertDraft.trade_id} onChange={(event) => setAlertDraft({ ...alertDraft, trade_id: event.target.value })} /> : <input type="number" step="0.01" placeholder="Threshold" value={alertDraft.threshold} onChange={(event) => setAlertDraft({ ...alertDraft, threshold: event.target.value })} />}<button className="primary-btn" type="submit">Add</button></form>
        <div className="alert-list">{alerts.map((alert) => <div className={alert.triggered ? "alert-triggered" : ""} key={alert.id}><span><strong>{alert.ticker} · {alert.alert_type.replaceAll("_", " ")}</strong><small>{alert.message || "Not checked yet"}</small></span><button className="danger-btn" type="button" onClick={() => removeAlert(alert.id)}>Delete</button></div>)}</div><p className="muted-text">Alerts check every minute while OrionTrader is open.</p></div>
        <div><div className="section-heading"><h3><Search size={17} /> {ticker} research</h3><button className="ghost-btn" type="button" onClick={refreshResearch}>Refresh</button></div>{research?.data_quality?.partial_failure && <p className="warning-text">One or more research feeds are stale or unavailable.</p>}<h4>Earnings calendar</h4><RecordList rows={research?.earnings?.earnings} empty="No earnings dates available." /><h4>Analyst ratings</h4><RecordList rows={research?.analyst_ratings?.summary?.length ? research.analyst_ratings.summary : research?.analyst_ratings?.recommendations} empty="No analyst ratings available." />{research?.analyst_ratings?.price_targets && <p className="muted-text">Price targets: {Object.entries(research.analyst_ratings.price_targets).map(([key, value]) => `${key} ${value}`).join(" · ")}</p>}<h4>Insider activity</h4><RecordList rows={research?.insider_activity?.transactions} empty="No insider transactions available." /></div></div>
      <p className="muted-text">Backtests are hypothetical and alerts are local planning aids. Neither feature places orders.</p>
    </section>
  );
}
