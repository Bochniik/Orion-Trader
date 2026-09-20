import { useEffect, useState } from "react";
import { Calculator, ShieldCheck } from "lucide-react";
import { getOrionTickerContext, simulateIntelligencePositionSize } from "../api/api";

const n = (v) => Number.isFinite(Number(v)) ? Number(v) : "";
const pick = (o, ...keys) => keys.map((k) => o?.[k]).find((v) => v !== null && v !== undefined && v !== "") ?? "";

export default function PositionSizingAssistant({ ticker }) {
  const [context, setContext] = useState(null);
  const [form, setForm] = useState({ entry_price:"", stop_price:"", risk_percent:1, max_allocation_percent:20, account_value:"", cash:"", atr:"", spread_percent:"", portfolio_correlation:"" });
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setContext(null); setResult(null); setError("");
    if (!ticker) return;
    let live = true;
    getOrionTickerContext(ticker).then((data) => {
      if (!live) return;
      setContext(data);
      const s = data?.setup || {};
      setForm((p) => ({ ...p,
        entry_price:n(pick(s,"entry_price","entry","reference_price")),
        stop_price:n(pick(s,"stop_loss","stop_price","invalidation_price")),
        account_value:n(data?.portfolio?.total_value),
        cash:n(data?.portfolio?.cash),
      }));
    }).catch((e) => live && setError(e?.message || "Ticker context unavailable."));
    return () => { live = false; };
  }, [ticker]);

  if (!ticker) return <section className="intelligence-module intelligence-module-empty"><Calculator size={24}/><h2>Position Sizing Assistant</h2><p>Select a ticker from the briefing first.</p></section>;

  const setup = context?.setup || {};
  const evidence = {
    liquidity_score: pick(setup,"liquidity_score"),
    setup_confidence: pick(setup,"confidence"),
    sector: pick(setup,"sector"),
    atr: pick(setup,"atr","atr_value"),
    spread_percent: pick(setup,"spread_percent","spread_pct"),
  };
  const set = (key) => (e) => setForm((p) => ({...p,[key]:e.target.value}));

  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(""); setResult(null);
    const payload = {
      ticker, entry_price:Number(form.entry_price), stop_price:Number(form.stop_price),
      risk_percent:Number(form.risk_percent), max_allocation_percent:Number(form.max_allocation_percent),
    };
    const optional = { account_value:form.account_value, cash:form.cash, atr:form.atr || evidence.atr, liquidity_score:evidence.liquidity_score, spread_percent:form.spread_percent || evidence.spread_percent, setup_confidence:evidence.setup_confidence, portfolio_correlation:form.portfolio_correlation };
    Object.entries(optional).forEach(([k,v]) => { if (v !== "" && v != null) payload[k] = Number(v); });
    if (evidence.sector) payload.sector = String(evidence.sector);
    try { setResult(await simulateIntelligencePositionSize(payload)); }
    catch (err) { setError(err?.message || "Could not calculate position size."); }
    finally { setBusy(false); }
  }

  return <section className="intelligence-module">
    <header className="intelligence-module-header"><div><p className="core-eyebrow">RISK ENGINE</p><h2>Position Sizing Assistant</h2><p>Stop-based sizing first; evidence can only reduce risk.</p></div><span className="intelligence-selected-chip">{ticker}</span></header>
    <form className="sizing-form" onSubmit={submit}>
      <label>Account value<input type="number" min="0" step=".01" value={form.account_value} onChange={set("account_value")} /></label>
      <label>Available cash<input type="number" min="0" step=".01" value={form.cash} onChange={set("cash")} /></label>
      <label>Entry<input required type="number" min="0" step=".0001" value={form.entry_price} onChange={set("entry_price")} /></label>
      <label>Stop / invalidation<input required type="number" min="0" step=".0001" value={form.stop_price} onChange={set("stop_price")} /></label>
      <label>Risk budget %<input required type="number" min=".01" max="20" step=".05" value={form.risk_percent} onChange={set("risk_percent")} /></label>
      <label>Max allocation %<input required type="number" min=".01" max="100" step=".5" value={form.max_allocation_percent} onChange={set("max_allocation_percent")} /></label>
      <label>ATR<input type="number" min="0" step=".0001" value={form.atr} onChange={set("atr")} placeholder={evidence.atr || "Optional"} /></label>
      <label>Spread %<input type="number" min="0" step=".001" value={form.spread_percent} onChange={set("spread_percent")} placeholder={evidence.spread_percent || "Optional"} /></label>
      <label>Portfolio correlation<input type="number" min="-1" max="1" step=".01" value={form.portfolio_correlation} onChange={set("portfolio_correlation")} placeholder="Optional -1 to 1" /></label>
      <button className="core-button sizing-submit" disabled={busy}>{busy ? "Calculating…" : "Calculate size"}</button>
    </form>
    <div className="sizing-evidence-strip"><span>Liquidity <strong>{evidence.liquidity_score || "Unavailable"}</strong></span><span>Confidence <strong>{evidence.setup_confidence || "Unavailable"}</strong></span><span>Sector <strong>{evidence.sector || "Unavailable"}</strong></span></div>
    {error && <div className="core-error" role="alert">{error}</div>}
    {result && <div className="sizing-result">
      <div className="sizing-result-grid">
        <div><span>Base size</span><strong>{result.base_position_size?.shares ?? 0} shares</strong><small>{"$"}{result.base_position_size?.position_cost ?? 0}</small></div>
        <div><span>Risk-adjusted</span><strong>{result.risk_adjusted_position_size?.shares ?? 0} shares</strong><small>{"$"}{result.risk_adjusted_position_size?.position_cost ?? 0}</small></div>
        <div><span>Max capital at risk</span><strong>{"$"}{result.maximum_capital_at_risk ?? 0}</strong><small>{result.account?.risk_budget_percent}% budget</small></div>
        <div><span>Loss at invalidation</span><strong>{"$"}{result.maximum_loss_at_invalidation ?? 0}</strong><small>{result.stop_distance_percent}% stop</small></div>
      </div>
      <div className="sizing-explanation"><ShieldCheck size={16}/><div><strong>{result.reductions?.length ? "Why Orion reduced the size" : "No additional risk haircut applied"}</strong>{result.reductions?.length ? <ul>{result.reductions.map((x,i)=><li key={i}>{x.reason}</li>)}</ul> : <p>Base stop/risk-budget sizing remains the active constraint.</p>}{result.missing_evidence?.length > 0 && <small>Unavailable evidence: {result.missing_evidence.join(", ")}.</small>}</div></div>
      <p className="sizing-semantics">{result.semantics}</p>
    </div>}
  </section>;
}
