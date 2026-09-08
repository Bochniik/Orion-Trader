import { useEffect, useMemo, useState } from "react";
import { Calculator, PieChart, Scale } from "lucide-react";
import { getPortfolioIntelligence, simulatePositionSize, simulateRebalance } from "../api/api";
import PerformanceChart from "./PerformanceChart";

function metric(value, suffix = "") {
  return value == null ? "Collecting data" : `${value}${suffix}`;
}

export default function PortfolioIntelligencePanel({ portfolio }) {
  const [benchmark, setBenchmark] = useState("SPY");
  const [benchmarkInput, setBenchmarkInput] = useState("SPY");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sizing, setSizing] = useState({ entry_price: 100, stop_price: 95, risk_percent: 1, max_allocation_percent: 20 });
  const [sizingResult, setSizingResult] = useState(null);
  const [targets, setTargets] = useState({ CASH: 100 });
  const [rebalanceResult, setRebalanceResult] = useState(null);
  const currency = portfolio?.currency || "USD";

  const positionKey = useMemo(
    () => Object.entries(portfolio?.positions || {})
      .map(([ticker, position]) => `${ticker}:${position.market_value}:${position.allocation_percent}`)
      .sort()
      .join("|"),
    [portfolio],
  );

  useEffect(() => {
    const currentTargets = { CASH: Number(((portfolio?.cash || 0) / (portfolio?.total_value || 1) * 100).toFixed(2)) };
    for (const [ticker, position] of Object.entries(portfolio?.positions || {})) currentTargets[ticker] = position.allocation_percent || 0;
    const total = Object.values(currentTargets).reduce((sum, value) => sum + value, 0);
    currentTargets.CASH = Number((currentTargets.CASH + (100 - total)).toFixed(2));
    setTargets(currentTargets);
  }, [positionKey, portfolio?.source, portfolio?.cash, portfolio?.total_value]);

  async function loadIntelligence() {
    try {
      setLoading(true); setError("");
      setData(await getPortfolioIntelligence(benchmark));
    } catch (loadError) { setError(loadError.message); }
    finally { setLoading(false); }
  }

  useEffect(() => { loadIntelligence(); }, [benchmark, positionKey, portfolio?.source, portfolio?.total_value]);

  async function runSizing(event) {
    event.preventDefault();
    try { setError(""); setSizingResult(await simulatePositionSize(Object.fromEntries(Object.entries(sizing).map(([key, value]) => [key, Number(value)])))); }
    catch (simulationError) { setError(simulationError.message); }
  }

  async function runRebalance(event) {
    event.preventDefault();
    try { setError(""); setRebalanceResult(await simulateRebalance(targets)); }
    catch (simulationError) { setError(simulationError.message); }
  }

  function changeBenchmark(event) {
    event.preventDefault();
    const clean = benchmarkInput.trim().toUpperCase();
    if (clean) setBenchmark(clean);
  }

  const performance = data?.performance || {};
  return (
    <section className="card portfolio-intelligence-card">
      <div className="card-title"><PieChart size={20} /> Portfolio intelligence</div>
      {loading && <p className="muted-text">Refreshing portfolio intelligence...</p>}
      {error && <p className="error-text">{error}</p>}

      <div className="portfolio-metrics intelligence-metrics">
        <div><span>Max drawdown</span><strong>{metric(performance.max_drawdown_percent, "%")}</strong></div>
        <div><span>Annual volatility</span><strong>{metric(performance.annualized_volatility_percent, "%")}</strong></div>
        <div><span>Sharpe ratio</span><strong>{metric(performance.sharpe_ratio)}</strong></div>
        <div><span>Total return</span><strong>{metric(performance.total_return_percent, "%")}</strong></div>
      </div>
      {performance.status === "collecting_history" && <p className="muted-text">Risk metrics need at least three daily equity snapshots. Orion has {performance.sample_days || 0} so far.</p>}

      <div className="intelligence-grid">
        <div><h3>Sector exposure</h3>{(data?.exposure?.sectors || []).map((row) => <div className="exposure-row" key={row.name}><span>{row.name}</span><div><i style={{ width: `${row.percent}%` }} /></div><strong>{row.percent}%</strong></div>)}</div>
        <div><h3>Asset classes</h3>{(data?.exposure?.asset_classes || []).map((row) => <div className="exposure-row" key={row.name}><span>{row.name}</span><div><i style={{ width: `${row.percent}%` }} /></div><strong>{row.percent}%</strong></div>)}</div>
      </div>

      <div className="benchmark-header"><h3>Performance comparison</h3><form onSubmit={changeBenchmark}><label>Benchmark <input value={benchmarkInput} maxLength={15} onChange={(event) => setBenchmarkInput(event.target.value.toUpperCase())} /></label><button className="ghost-btn" type="submit">Compare</button></form></div>
      <div className="chart-legend"><span className="portfolio-line">Portfolio</span><span className="benchmark-line">{data?.comparison?.symbol || benchmark}</span></div>
      <PerformanceChart comparison={data?.comparison} />

      <div className="simulator-grid">
        <form onSubmit={runSizing}><h3><Calculator size={17} /> Position sizing</h3>
          {Object.entries({ entry_price: "Entry price", stop_price: "Stop price", risk_percent: "Risk %", max_allocation_percent: "Max allocation %" }).map(([key, label]) => <label key={key}>{label}<input type="number" min="0.01" step="0.01" value={sizing[key]} onChange={(event) => setSizing({ ...sizing, [key]: event.target.value })} /></label>)}
          <button className="primary-btn" type="submit">Calculate size</button>
          {sizingResult && <p><strong>{sizingResult.recommended_shares} shares</strong> · {sizingResult.position_cost.toLocaleString(undefined, { style: "currency", currency })} · limited by {sizingResult.limiting_factor}</p>}
        </form>
        <form onSubmit={runRebalance}><h3><Scale size={17} /> Rebalancing targets</h3>
          {Object.entries(targets).map(([ticker, weight]) => <label key={ticker}>{ticker} %<input type="number" min="0" max="100" step="0.01" value={weight} onChange={(event) => setTargets({ ...targets, [ticker]: Number(event.target.value) })} /></label>)}
          <p className="muted-text">Target total: {Object.values(targets).reduce((sum, value) => sum + Number(value), 0).toFixed(2)}%</p>
          <button className="primary-btn" type="submit">Simulate rebalance</button>
          {rebalanceResult && <div className="rebalance-actions">{rebalanceResult.actions.map((action) => <p key={action.ticker}><strong>{action.action} {action.ticker}</strong> · {Math.abs(action.delta_value).toLocaleString(undefined, { style: "currency", currency })}{action.estimated_shares != null ? ` (~${action.estimated_shares} shares)` : ""}</p>)}</div>}
        </form>
      </div>
      <p className="muted-text">Simulators are planning tools only and never place trades.</p>
    </section>
  );
}
