import React, { useEffect, useState } from "react";
import {
  AlertTriangle, Ban, Calculator, Clock3, Eraser, Gauge,
  RefreshCw, ShieldAlert, ShieldCheck, Waves,
} from "lucide-react";
import {
  deleteExecutionStressHistory,
  getExecutionStressHistory,
  getExecutionStressSimulation,
  runExecutionStressSimulation,
} from "../api/api";

const DEFAULT_PLAN = {
  symbol: "AAPL",
  side: "buy",
  order_type: "market",
  quantity: "100",
  reference_price: "100",
  daily_volume: "1000000",
  spread_bps: "10",
  base_slippage_bps: "5",
  max_participation_percent: "1",
  adverse_gap_percent: "8",
  luld_style_band_percent: "5",
  limit_price: "",
  protective_stop_price: "95",
};

function number(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function money(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function date(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function statusLabel(status) {
  return {
    filled: "Full fill",
    partial_fill: "Partial fill",
    limit_not_marketable: "No limit fill",
    paused_no_immediate_fill: "Paused",
    rejected: "Rejected",
  }[status] || status;
}

function ScenarioCard({ item }) {
  const blocked = item.average_fill_price == null;
  return <article className={`execution-scenario ${item.severity} ${blocked ? "blocked" : ""}`}>
    <header>
      <div><span>{item.severity}</span><h4>{item.label}</h4></div>
      <strong>{statusLabel(item.status)}</strong>
    </header>
    <div className="execution-scenario-metrics">
      <div><span>Fill</span><strong>{number(item.fill_ratio_percent)}%</strong><small>{number(item.filled_quantity, 6)} / {number(item.requested_quantity, 6)} shares</small></div>
      <div><span>Average price</span><strong>{money(item.average_fill_price)}</strong><small>Arrival {money(item.arrival_price)}</small></div>
      <div><span>Shortfall</span><strong>{item.implementation_shortfall_bps == null ? "Unknown" : `${number(item.implementation_shortfall_bps)} bps`}</strong><small>{money(item.implementation_shortfall)}</small></div>
      <div><span>Spread + impact</span><strong>{item.spread_bps == null ? "—" : `${number(item.spread_bps)} + ${number(item.impact_bps)} bps`}</strong><small>{number(item.participation_percent, 4)}% daily volume</small></div>
    </div>
    <p>{item.explanation}</p>
    {item.stop_stress && <details><summary>Protective-stop stress</summary><div className="execution-stop-audit"><span>Planned stop <strong>{money(item.stop_stress.planned_stop_price)}</strong></span><span>Modeled fill <strong>{money(item.stop_stress.modeled_stop_fill_price)}</strong></span><span>Risk/share <strong>{money(item.stop_stress.stressed_risk_per_share)}</strong></span><span>Expansion <strong>{number(item.stop_stress.risk_expansion_multiple, 3)}×</strong></span></div><p>{item.stop_stress.disclosure}</p></details>}
  </article>;
}

export default function ExecutionSimulationPanel({ initialTicker = "AAPL", initialPlan = null }) {
  const [plan, setPlan] = useState({ ...DEFAULT_PLAN, symbol: initialTicker || "AAPL", ...(initialPlan || {}) });
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadHistory() {
    try {
      const payload = await getExecutionStressHistory(20);
      setHistory(payload.simulations || []);
    } catch (loadError) {
      setError(loadError.message);
    }
  }

  useEffect(() => { loadHistory(); }, []);
  useEffect(() => {
    if (initialTicker) setPlan((current) => ({ ...current, symbol: initialTicker }));
  }, [initialTicker]);
  useEffect(() => {
    if (!initialPlan) return;
    setPlan((current) => ({
      ...current,
      ...Object.fromEntries(
        Object.entries(initialPlan).map(([key, value]) => [key, value == null ? "" : String(value)])
      ),
    }));
  }, [initialPlan]);

  function update(event) {
    const { name, value } = event.target;
    setPlan((current) => {
      const next = { ...current, [name]: value };
      if (name === "order_type" && value === "market") next.limit_price = "";
      if (name === "order_type" && value === "limit" && !next.limit_price) next.limit_price = next.reference_price;
      if (name === "side") next.protective_stop_price = "";
      return next;
    });
  }

  function payload() {
    const numeric = [
      "quantity", "reference_price", "daily_volume", "spread_bps",
      "base_slippage_bps", "max_participation_percent",
      "adverse_gap_percent", "luld_style_band_percent",
    ];
    const next = { ...plan, symbol: plan.symbol.trim().toUpperCase() };
    numeric.forEach((key) => { next[key] = Number(next[key]); });
    next.limit_price = plan.order_type === "limit" ? Number(plan.limit_price) : null;
    next.protective_stop_price = plan.protective_stop_price === "" ? null : Number(plan.protective_stop_price);
    return next;
  }

  async function run(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const next = await runExecutionStressSimulation(payload());
      setResult(next);
      await loadHistory();
    } catch (runError) {
      setError(runError.message);
    } finally {
      setLoading(false);
    }
  }

  async function restore(simulationId) {
    setLoading(true);
    setError("");
    try {
      const next = await getExecutionStressSimulation(simulationId);
      setResult(next);
      setPlan((current) => ({
        ...current,
        ...Object.fromEntries(Object.entries(next.plan || {}).map(([key, value]) => [key, value == null ? "" : String(value)])),
      }));
    } catch (restoreError) {
      setError(restoreError.message);
    } finally {
      setLoading(false);
    }
  }

  async function clearHistory() {
    if (!globalThis.confirm?.("Clear saved Execution Lab simulations? Replay Lab and Move Lab evidence stay unchanged.")) return;
    try {
      await deleteExecutionStressHistory();
      setHistory([]);
      setResult(null);
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  return <section className="execution-lab-workspace">
    <div className="card execution-intro">
      <div className="move-lab-title"><div><Gauge size={22} /><span>Execution Stress Lab · v1</span><h2>Find out whether a good chart survives a bad fill</h2></div><span className="research-only-badge">ZERO ORDER ROUTES</span></div>
      <p>Test one hypothetical stock plan against spread, market impact, partial-fill, opening-gap, rejection and volatility-interruption assumptions. Every number is reproducible; no scenario likelihood is invented.</p>
      <div className="execution-contract-grid">
        <div><Calculator size={16} /><span>Method</span><strong>Deterministic matrix</strong><small>Seven visible scenarios</small></div>
        <div><Waves size={16} /><span>Liquidity</span><strong>Capacity-constrained</strong><small>No queue-priority fiction</small></div>
        <div><Ban size={16} /><span>Orders</span><strong>Impossible here</strong><small>No credentials or broker calls</small></div>
      </div>
    </div>

    <form className="card execution-controls" onSubmit={run}>
      <div className="section-heading"><div><h3>Hypothetical execution plan</h3><p>Use a recent average daily volume—not today’s partial volume. Prices and liquidity are manual assumptions, not a live quote.</p></div><button className="primary" type="submit" disabled={loading}><RefreshCw size={16} className={loading ? "spin" : ""} />{loading ? "Stressing…" : "Run stress matrix"}</button></div>
      <div className="execution-form-grid">
        <label>Symbol<input name="symbol" value={plan.symbol} onChange={update} maxLength={15} required /></label>
        <label>Side<select name="side" value={plan.side} onChange={update}><option value="buy">Buy / long entry</option><option value="sell">Sell / short entry</option></select></label>
        <label>Order type<select name="order_type" value={plan.order_type} onChange={update}><option value="market">Market</option><option value="limit">Limit</option></select></label>
        <label>Quantity<input name="quantity" type="number" min="0.000001" step="any" value={plan.quantity} onChange={update} required /></label>
        <label>Decision price $<input name="reference_price" type="number" min="0.000001" step="any" value={plan.reference_price} onChange={update} required /></label>
        <label>Average daily volume<input name="daily_volume" type="number" min="1" step="1" value={plan.daily_volume} onChange={update} required /></label>
        <label>Observed spread (bps)<input name="spread_bps" type="number" min="0" step="any" value={plan.spread_bps} onChange={update} required /></label>
        <label>Base slippage (bps)<input name="base_slippage_bps" type="number" min="0" step="any" value={plan.base_slippage_bps} onChange={update} required /></label>
        <label>Max participation %<input name="max_participation_percent" type="number" min="0.0001" max="100" step="any" value={plan.max_participation_percent} onChange={update} required /></label>
        <label>Adverse gap stress %<input name="adverse_gap_percent" type="number" min="0" max="99" step="any" value={plan.adverse_gap_percent} onChange={update} required /></label>
        <label>LULD-style band stress %<input name="luld_style_band_percent" type="number" min="0.1" max="100" step="any" value={plan.luld_style_band_percent} onChange={update} required /></label>
        {plan.order_type === "limit" && <label>Limit price $<input name="limit_price" type="number" min="0.000001" step="any" value={plan.limit_price} onChange={update} required /></label>}
        <label>Protective stop $ <small>optional</small><input name="protective_stop_price" type="number" min="0.000001" step="any" value={plan.protective_stop_price} onChange={update} /></label>
      </div>
      {error && <div className="error">{error}</div>}
    </form>

    {result && <>
      <div className="card execution-summary">
        <div className="section-heading"><div><h3>{result.symbol} execution stress summary</h3><p>{result.plan?.side?.toUpperCase()} {number(result.plan?.quantity, 6)} · {result.plan?.order_type} · {money(result.plan?.reference_price)} decision reference</p></div><span className="unvalidated-badge">ASSUMPTION-DRIVEN</span></div>
        <div className="execution-summary-grid">
          <div><span>Requested notional</span><strong>{money(result.summary?.requested_notional)}</strong><small>Planning value only</small></div>
          <div><span>Baseline fill</span><strong>{number(result.summary?.baseline_fill_ratio_percent)}%</strong><small>{result.summary?.baseline_shortfall_bps == null ? "Unknown cost" : `${number(result.summary?.baseline_shortfall_bps)} bps shortfall`}</small></div>
          <div><span>Partial scenarios</span><strong>{number(result.summary?.partial_fill_scenarios, 0)}</strong><small>of {number(result.summary?.scenario_count, 0)} scenarios</small></div>
          <div><span>Blocked / no fill</span><strong>{number(result.summary?.blocked_or_no_fill_scenarios, 0)}</strong><small>No zero-cost assumption</small></div>
          <div><span>Worst filled case</span><strong>{result.summary?.worst_filled_scenario?.label || "—"}</strong><small>{result.summary?.worst_filled_scenario ? `${number(result.summary.worst_filled_scenario.implementation_shortfall_bps)} bps` : "No modeled fill"}</small></div>
        </div>
      </div>
      <div className="execution-scenario-grid">{(result.scenarios || []).map((item) => <ScenarioCard key={item.id} item={item} />)}</div>
      <div className="card execution-audit">
        <div><h3><ShieldAlert size={17} /> Model audit and official-rule boundary</h3><p>{result.regulatory_context?.note}</p><p>The interruption scenario blocks immediate execution. It does not calculate an official historical band or invent a reopening price.</p></div>
        <details><summary>Formula audit</summary><ul>{Object.entries(result.formula_audit || {}).map(([key, value]) => <li key={key}><strong>{key.replaceAll("_", " ")}</strong>{value}</li>)}</ul></details>
        <details><summary>Known limitations</summary><ul>{(result.limitations || []).map((item) => <li key={item}>{item}</li>)}</ul></details>
        <footer><ShieldCheck size={14} />{result.safety_boundary}</footer>
      </div>
    </>}

    <div className="card execution-history">
      <div className="section-heading"><div><h3><Clock3 size={17} /> Execution Lab history</h3><p>Lists load the compact plan and summary first; open a run to restore its full scenario audit.</p></div><button className="ghost-btn danger-btn" type="button" onClick={clearHistory} disabled={!history.length}><Eraser size={15} /> Clear simulations</button></div>
      <div>{history.map((item) => <button type="button" className={item.history_id === result?.history_id ? "active" : ""} key={item.history_id} onClick={() => restore(item.history_id)}><strong>{item.symbol} · {date(item.saved_at)}</strong><span>{item.plan?.side} {number(item.plan?.quantity, 6)} · {money(item.plan?.reference_price)} · {number(item.summary?.blocked_or_no_fill_scenarios, 0)} blocked/no-fill</span></button>)}</div>
      {!history.length && <p className="empty-state">No saved execution simulations yet.</p>}
    </div>
  </section>;
}
