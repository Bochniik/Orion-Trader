import React, { useEffect, useState } from "react";
import {
  Activity, AlertTriangle, BrainCircuit, CheckCircle2, Database,
  FlaskConical, Gauge, RefreshCw, Search, ShieldCheck, Sparkles, Trash2,
} from "lucide-react";
import {
  deletePredictiveLearningMemory,
  deletePredictivePredictions,
  explainPredictivePrediction,
  getPredictiveAnalytics,
  getPredictiveIntelligenceStatus,
  getPredictiveLearningMemory,
  getPredictiveModels,
  getPredictivePredictions,
  scanLiveEdge,
  settlePredictiveOutcomes,
  trainPredictiveModel,
} from "../api/api";

const HORIZONS = ["1m", "3m", "5m", "15m", "30m", "1h"];

function percent(value, digits = 1) {
  return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : "—";
}

function number(value, digits = 2) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
}

function EdgeCard({ row, onOpenTicker, onExplain, explanation, busy }) {
  const noTrade = row.direction === "NO_TRADE";
  const levels = row.levels || {};
  const strategy = row.strategy_consensus || {};
  const learned = row.learning_memory || {};
  return <article className={`edge-card ${noTrade ? "edge-card-muted" : "edge-card-active"}`}>
    <header>
      <button type="button" className="ticker-link" onClick={() => onOpenTicker?.(row.ticker)}>{row.ticker}</button>
      <span className={`edge-direction ${noTrade ? "neutral" : row.direction?.toLowerCase()}`}>{row.verdict}</span>
      <b>{row.decision || "HOLD"} · {row.horizon}</b>
    </header>
    <div className="edge-probabilities">
      <span><small>UP</small><strong>{percent(row.P_UP)}</strong></span>
      <span><small>DOWN</small><strong>{percent(row.P_DOWN)}</strong></span>
      <span><small>NEUTRAL</small><strong>{percent(row.P_NEUTRAL)}</strong></span>
      <span><small>EDGE SCORE</small><strong>{row.opportunity_score?.score ?? "—"}</strong></span>
    </div>
    <div className="edge-evidence-grid">
      <span>Expected move <b>{number(row.expected_move_percent)}%</b></span>
      <span>Selected EV <b>{number(row.model_direction === "UP" ? row.expected_value?.EV_LONG_bps : row.expected_value?.EV_SHORT_bps)} bps</b></span>
      <span>Liquidity <b>{row.liquidity_tier || "—"} · {number(row.liquidity_score, 0)}</b></span>
      <span>Relative volume <b>{number(row.relative_volume)}×</b></span>
      <span>VWAP <b>{row.vwap_status || "—"}</b></span>
      <span>Regime <b>{row.market_regime?.label || "—"}</b></span>
      <span>Strategy consensus <b>{strategy.consensus || "—"} · {number(strategy.agreement_score, 0)}</b></span>
      <span>Learning memory <b>{learned.memory_state?.replaceAll("_", " ") || "cold start"} · {learned.outcome_events || 0}</b></span>
    </div>
    <p>{row.short_explanation}</p>
    <div className="edge-levels">
      <span>Entry <b>{levels.entry_area?.join(" – ") || "Withheld"}</b></span>
      <span>Invalidation <b>{levels.invalidation_level ?? "Withheld"}</b></span>
      <span>Target <b>{levels.target_area?.join(" – ") || "Withheld"}</b></span>
    </div>
    {row.blockers?.length > 0 && <details><summary>Why Orion withheld the trade</summary><ul>{row.blockers.map((item) => <li key={item}>{item}</li>)}</ul></details>}
    {strategy.strategies?.length > 0 && <details className="strategy-consensus-audit"><summary>{strategy.available_strategies} of {strategy.strategy_count} mathematical strategies had usable data</summary><div>{strategy.strategies.map((item) => <span key={item.id} className={`strategy-vote ${item.state?.toLowerCase()}`}><b>{item.name}</b><small>{item.state} · {number(item.strength, 0)} strength · {number(item.learned_multiplier, 2)}× learned weight</small></span>)}</div><p>{strategy.semantics}</p></details>}
    {learned.lessons?.length > 0 && <details><summary>What Orion remembers</summary><ul>{learned.lessons.map((item) => <li key={item}>{item}</li>)}</ul></details>}
    <footer>
      <span className="model-confidence">{row.confidence?.replaceAll("_", " ")}</span>
      <button type="button" className="soft-button" disabled={busy} onClick={() => onExplain(row.prediction_id)}><Sparkles size={15} /> Explain</button>
    </footer>
    {explanation && <div className="edge-ai-explanation"><b>Orion explanation</b><p>{explanation.explanation?.summary}</p><small>Deterministic values preserved · SHA-256 {explanation.deterministic_sha256?.slice(0, 12)}…</small></div>}
  </article>;
}

function Metric({ label, value, hint }) {
  return <div className="lab-metric"><small>{label}</small><strong>{value}</strong>{hint && <span>{hint}</span>}</div>;
}

export default function PredictiveIntelligencePanel({ ticker = "", alpacaConnected, onOpenBroker, onOpenTicker }) {
  const [mode, setMode] = useState("edge");
  const [status, setStatus] = useState(null);
  const [models, setModels] = useState([]);
  const [board, setBoard] = useState(null);
  const [predictions, setPredictions] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [learningMemory, setLearningMemory] = useState(null);
  const [selectedHorizons, setSelectedHorizons] = useState(["1m", "3m", "5m", "15m"]);
  const [candidateCount, setCandidateCount] = useState(12);
  const [scanMode, setScanMode] = useState("market");
  const [tickerInput, setTickerInput] = useState(String(ticker || "").toUpperCase());
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [explanations, setExplanations] = useState({});

  async function refresh() {
    setBusy("refresh"); setMessage("");
    try {
      const [nextStatus, nextModels, nextPredictions, nextAnalytics, nextMemory] = await Promise.all([
        getPredictiveIntelligenceStatus(), getPredictiveModels(10),
        getPredictivePredictions(100), getPredictiveAnalytics(),
        getPredictiveLearningMemory(tickerInput),
      ]);
      setStatus(nextStatus); setModels(nextModels.models || []);
      setPredictions(nextPredictions.predictions || []); setAnalytics(nextAnalytics); setLearningMemory(nextMemory);
    } catch (error) { setMessage(error.message); }
    finally { setBusy(""); }
  }

  useEffect(() => { refresh(); }, []);

  async function train() {
    setBusy("train"); setMessage("");
    try {
      const result = await trainPredictiveModel({ candidate_count: 24, training_symbol_count: 8, name: "Orion calibrated baseline" });
      setMessage(`Baseline ${result.status}. ${result.dataset.sample_count.toLocaleString()} leakage-safe samples built.`);
      await refresh();
    } catch (error) { setMessage(error.message); setBusy(""); }
  }

  async function scan() {
    setBusy("scan"); setMessage("");
    try {
      const selectedTicker = tickerInput.trim().toUpperCase();
      if (scanMode === "single" && !/^[A-Z0-9.\-]{1,15}$/.test(selectedTicker)) throw new Error("Enter a valid ticker before analyzing one stock.");
      const result = await scanLiveEdge({ candidate_count: candidateCount, horizons: selectedHorizons, symbols: scanMode === "single" ? [selectedTicker] : [] });
      setBoard(result);
      setMessage(result.empty_edge_message || `${result.liquidity_candidates_ranked || 0} securities ranked by liquidity; ${result.summary?.predictions || 0} horizon candidates analyzed.`);
      const [next, nextMemory] = await Promise.all([getPredictivePredictions(100), getPredictiveLearningMemory(scanMode === "single" ? selectedTicker : "")]);
      setPredictions(next.predictions || []);
      setLearningMemory(nextMemory);
    } catch (error) { setMessage(error.message); }
    finally { setBusy(""); }
  }

  async function settle() {
    setBusy("settle"); setMessage("");
    try {
      const result = await settlePredictiveOutcomes();
      setAnalytics(result.analytics); setMessage(`${result.settled} outcomes settled; ${result.still_pending} still pending.`);
      const [next, nextMemory] = await Promise.all([getPredictivePredictions(100), getPredictiveLearningMemory(tickerInput)]); setPredictions(next.predictions || []); setLearningMemory(nextMemory);
    } catch (error) { setMessage(error.message); }
    finally { setBusy(""); }
  }

  async function clearHistory() {
    if (!window.confirm("Remove all stored live predictions and laboratory outcomes? Model runs are preserved.")) return;
    setBusy("clear");
    try { await deletePredictivePredictions(); setPredictions([]); setAnalytics(null); setBoard(null); setMessage("Prediction history removed. Models and learned outcome memory were preserved."); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(""); }
  }

  async function clearLearningMemory() {
    if (!window.confirm("Remove Orion's learned good/bad outcome memory? Models and prediction history will remain.")) return;
    setBusy("clear-memory");
    try { await deletePredictiveLearningMemory(); const next = await getPredictiveLearningMemory(tickerInput); setLearningMemory(next); setMessage("Outcome-learning memory removed. Models and prediction history were preserved."); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(""); }
  }

  async function explain(predictionId) {
    setBusy(`explain-${predictionId}`);
    try {
      const result = await explainPredictivePrediction(predictionId);
      setExplanations((current) => ({ ...current, [predictionId]: result }));
    }
    catch (error) { setMessage(error.message); }
    finally { setBusy(""); }
  }

  const latestModel = models[0] || status?.active_model;
  const overall = analytics?.overall || {};

  return <section className="predictive-shell">
    <div className="predictive-hero">
      <div><span className="eyebrow"><BrainCircuit size={17} /> ORION PREDICTIVE INTELLIGENCE</span><h2>Probability, cost and liquidity—not certainty</h2><p>Interpretable models calculate calibrated outcomes. Orion AI can explain them, but cannot change a number or place an order.</p></div>
      <span className="research-only-badge"><ShieldCheck size={15} /> ASSISTANT ONLY</span>
    </div>

    <div className="predictive-tabs">
      <button type="button" className={mode === "edge" ? "active" : ""} onClick={() => setMode("edge")}><Gauge size={17} /> Orion Live Edge</button>
      <button type="button" className={mode === "lab" ? "active" : ""} onClick={() => setMode("lab")}><FlaskConical size={17} /> Prediction Laboratory</button>
    </div>

    {!alpacaConnected && <div className="predictive-callout warning"><AlertTriangle size={19} /><div><b>Alpaca research data is disconnected</b><span>Connect the paper account for tradable-universe discovery and quote snapshots. This does not enable orders.</span></div><button type="button" onClick={onOpenBroker}>Open Paper Lab</button></div>}
    {message && <div className="predictive-message">{message}</div>}

    {mode === "edge" && <>
      <div className="predictive-controls">
        <div><small>ACTIVE BASELINE</small><strong>{latestModel?.name || "Not built"}</strong><span>{latestModel?.status?.replaceAll("_", " ") || "Train before scanning"}</span></div>
        <div className="edge-selection-control"><small>ANALYSIS TARGET</small><div><button type="button" className={scanMode === "market" ? "active" : ""} onClick={() => setScanMode("market")}>Liquidity-first market</button><button type="button" className={scanMode === "single" ? "active" : ""} onClick={() => setScanMode("single")}>Chosen stock</button></div>{scanMode === "single" ? <label><Search size={15} /><input aria-label="Chosen stock ticker" maxLength={15} placeholder="AAPL" value={tickerInput} onChange={(event) => setTickerInput(event.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g, ""))} /></label> : <span>Orion ranks up to one hundred candidates and analyzes the most liquid names first.</span>}</div>
        {scanMode === "market" && <label>Results to analyze<input type="number" min="3" max="30" value={candidateCount} onChange={(event) => setCandidateCount(Math.max(3, Math.min(30, Number(event.target.value) || 3)))} /></label>}
        <div className="horizon-picker"><small>HORIZONS</small>{HORIZONS.map((horizon) => <label key={horizon}><input type="checkbox" checked={selectedHorizons.includes(horizon)} onChange={() => setSelectedHorizons((current) => current.includes(horizon) ? current.filter((item) => item !== horizon) : [...current, horizon])} />{horizon}</label>)}</div>
        <button type="button" className="soft-button" disabled={Boolean(busy)} onClick={train}><Database size={17} /> {busy === "train" ? "Building…" : "Build / validate baseline"}</button>
        <button type="button" className="primary-button" disabled={Boolean(busy) || !alpacaConnected || !latestModel || !selectedHorizons.length} onClick={scan}><Activity size={17} /> {busy === "scan" ? "Scanning…" : "Scan Live Edge"}</button>
      </div>
      {board && <><div className="liquidity-policy-ribbon"><strong>LIQUIDITY FIRST</strong><span>{board.liquidity_candidates_ranked || 0} candidates ranked · {board.selection_mode === "selected_tickers" ? `selected: ${board.selected_tickers?.join(", ")}` : "highest absolute liquidity first"}</span><small>{board.ranking_policy}</small></div><div className="regime-ribbon"><span>MARKET REGIME</span><strong>{board.market_regime?.label}</strong><small>{number(board.market_regime?.confidence, 0)}% classification confidence · current state, not a forecast</small></div></>}
      {!board && <div className="predictive-empty"><BrainCircuit size={28} /><h3>No live board yet</h3><p>Build a baseline, then scan. Unvalidated horizons remain NO TRADE even when probabilities can be calculated.</p></div>}
      {board?.highest_statistical_edge?.length > 0 && <div className="edge-section"><h3><CheckCircle2 size={19} /> Highest Statistical Edge</h3><p>Tier A and B liquidity receives priority.</p><div className="edge-card-grid">{board.highest_statistical_edge.map((row) => <EdgeCard key={row.prediction_id} row={row} onOpenTicker={onOpenTicker} onExplain={explain} explanation={explanations[row.prediction_id]} busy={busy === `explain-${row.prediction_id}`} />)}</div></div>}
      {board?.liquid_research_watch?.length > 0 && <div className="edge-section liquid-watch"><h3><Gauge size={19} /> High-Liquidity Research Watch</h3><p>Tier A/B names remain visible even when model, cost, strategy or memory gates correctly return HOLD / NO TRADE.</p><div className="edge-card-grid">{board.liquid_research_watch.map((row) => <EdgeCard key={row.prediction_id} row={row} onOpenTicker={onOpenTicker} onExplain={explain} explanation={explanations[row.prediction_id]} busy={busy === `explain-${row.prediction_id}`} />)}</div></div>}
      {board?.higher_risk_lower_liquidity?.length > 0 && <div className="edge-section elevated"><h3><AlertTriangle size={19} /> Higher-Risk / Lower-Liquidity</h3><p>Tier C and D candidates require stronger evidence and display tighter fail-closed gates.</p><div className="edge-card-grid">{board.higher_risk_lower_liquidity.map((row) => <EdgeCard key={row.prediction_id} row={row} onOpenTicker={onOpenTicker} onExplain={explain} explanation={explanations[row.prediction_id]} busy={busy === `explain-${row.prediction_id}`} />)}</div></div>}
      {board?.no_trade?.length > 0 && <details className="lower-liquidity-no-trade"><summary>{board.no_trade.length} lower-liquidity NO TRADE results</summary><p>These Tier C/D observations are retained for audit and learning, but never displace the liquid board.</p><div className="edge-card-grid">{board.no_trade.map((row) => <EdgeCard key={row.prediction_id} row={row} onOpenTicker={onOpenTicker} onExplain={explain} explanation={explanations[row.prediction_id]} busy={busy === `explain-${row.prediction_id}`} />)}</div></details>}
      {board?.unavailable_predictions?.length > 0 && <details className="predictive-unavailable"><summary>{board.unavailable_predictions.length} unavailable horizon results</summary><p>One-minute history is never relabeled as sub-minute evidence. Build true sub-minute observations before the thirty-second horizon can exist.</p></details>}
    </>}

    {mode === "lab" && <>
      <div className="lab-toolbar"><button type="button" className="primary-button" disabled={Boolean(busy)} onClick={settle}><RefreshCw size={17} /> Observe due outcomes</button><button type="button" className="soft-button" disabled={Boolean(busy)} onClick={refresh}><RefreshCw size={17} /> Refresh</button><button type="button" className="danger-button" disabled={Boolean(busy) || predictions.length === 0} onClick={clearHistory}><Trash2 size={17} /> Remove history</button><button type="button" className="danger-button" disabled={Boolean(busy) || !learningMemory?.outcome_events} onClick={clearLearningMemory}><Trash2 size={17} /> Clear learned memory</button></div>
      <div className="lab-metrics">
        <Metric label="SETTLED OBSERVATIONS" value={overall.observations ?? 0} hint="Five hundred required for stable reporting" />
        <Metric label="OVERALL ACCURACY" value={percent(overall.accuracy)} hint="Never evaluate accuracy alone" />
        <Metric label="BRIER SCORE" value={number(overall.brier_score, 4)} hint="Lower is better" />
        <Metric label="AFTER-COST SIMULATED P&L" value={percent(overall.simulated_pnl_after_costs, 2)} hint="Research simulation only" />
      </div>
      <div className="laboratory-grid">
        <article><h3>Baseline validation</h3>{latestModel ? <div className="horizon-table">{Object.entries(latestModel.horizon_status || {}).map(([horizon, value]) => <div key={horizon}><b>{horizon}</b><span>{value.sample_count ?? 0} samples</span><em className={value.reliable ? "passed" : "withheld"}>{value.reliable ? "Passed gates" : value.status?.replaceAll("_", " ")}</em></div>)}</div> : <p>No model run exists.</p>}</article>
        <article><h3>Reliability state</h3><p>{analytics?.reliability_message || "Outcomes have not been collected yet."}</p><ul><li>Chronological train, calibration and untouched holdout blocks</li><li>Expanding walk-forward evaluation</li><li>Execution costs included before edge ranking</li><li>No neural network and no random split</li></ul></article>
      </div>
      <article className="learning-brain-panel"><header><div><span className="eyebrow"><BrainCircuit size={16} /> ORION LEARNING BRAIN</span><h3>Good and bad outcomes become bounded decision memory</h3></div><strong>{learningMemory?.memory_state?.replaceAll("_", " ") || "cold start"}</strong></header><div className="learning-brain-metrics"><Metric label="REMEMBERED OUTCOMES" value={learningMemory?.outcome_events || 0} /><Metric label="BAYESIAN ACCURACY" value={percent(learningMemory?.decision_profile?.bayesian_forecast_accuracy)} /><Metric label="AFTER-COST RETURN" value={percent(learningMemory?.decision_profile?.average_after_cost_return, 3)} /><Metric label="MEMORY INFLUENCE" value={learningMemory?.decision_influence?.replaceAll("_", " ") || "cold start"} /></div><ul>{(learningMemory?.lessons || []).map((item) => <li key={item}>{item}</li>)}</ul><p>Memory can down-weight historically weak strategies or veto an adverse pattern. It cannot rewrite calibrated probabilities, bypass liquidity/cost gates, or place an order.</p></article>
      <div className="prediction-history"><header><h3>Prediction history</h3><span>{predictions.length} loaded · {analytics?.pending_predictions || 0} pending</span></header>{predictions.length ? <div className="prediction-table"><div className="table-head"><span>Time</span><span>Ticker</span><span>Horizon</span><span>Verdict</span><span>Probabilities</span><span>Outcome</span></div>{predictions.map((row) => <div key={row.prediction_id}><span>{new Date(row.timestamp).toLocaleString()}</span><button type="button" onClick={() => onOpenTicker?.(row.ticker)}>{row.ticker}</button><span>{row.horizon}</span><span>{row.verdict}</span><span>↑ {percent(row.P_UP)} · ↓ {percent(row.P_DOWN)} · — {percent(row.P_NEUTRAL)}</span><span>{row.outcome_status === "settled" ? `${row.actual_direction} · ${percent(row.actual_return, 2)}` : "Pending"}</span></div>)}</div> : <p className="empty-copy">No saved predictions. Run Live Edge to begin the audit trail.</p>}</div>
    </>}
  </section>;
}
