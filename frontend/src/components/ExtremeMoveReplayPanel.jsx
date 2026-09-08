import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Clock3, Eraser, FlaskConical, RefreshCw, ShieldCheck, Target, TrendingUp } from "lucide-react";
import {
  deleteExtremeMoveReplayHistory,
  getExtremeMoveReplay,
  getExtremeMoveReplayHistory,
  runExtremeMoveReplay,
} from "../api/api";

const DEFAULT_CONFIG = {
  ticker: "AAPL",
  period: "5y",
  forward_sessions: 20,
  stride_sessions: 5,
  minimum_score: 60,
};

function number(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function date(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString();
}

function ReturnPath({ path = [] }) {
  const geometry = useMemo(() => {
    if (!path.length) return null;
    const values = path.map((point) => Number(point.close_return_percent || 0));
    const lows = path.map((point) => Number(point.low_return_percent || 0));
    const highs = path.map((point) => Number(point.high_return_percent || 0));
    const minimum = Math.min(-5, ...lows);
    const maximum = Math.max(20, ...highs);
    const span = Math.max(1, maximum - minimum);
    const y = (value) => 96 - ((value - minimum) / span) * 82;
    const points = values.map((value, index) => `${12 + index / Math.max(1, values.length - 1) * 336},${y(value)}`).join(" ");
    return { minimum, maximum, y, points };
  }, [path]);
  if (!geometry) return null;
  return <svg className="replay-path" viewBox="0 0 360 110" role="img" aria-label="Forward close-return path">
    {[0, 20, 50, 100].filter((value) => value >= geometry.minimum && value <= geometry.maximum).map((value) => <g key={value}><line x1="12" x2="348" y1={geometry.y(value)} y2={geometry.y(value)} /><text x="14" y={geometry.y(value) - 3}>{value}%</text></g>)}
    <polyline points={geometry.points} fill="none" stroke="#22d3ee" strokeWidth="3" vectorEffect="non-scaling-stroke" />
  </svg>;
}

function ReplayExample({ item, onOpenTicker, onStressExecution, symbol }) {
  const outcome = item.outcome || {};
  const score = item.preparation_score || {};
  return <article className="replay-example">
    <header><div><span>{date(item.anchor_date)} decision close</span><strong>{score.score ?? "—"}/100 preparation</strong></div><div><span>Maximum observed high</span><strong>+{number(outcome.maximum_gain_percent)}%</strong></div></header>
    <ReturnPath path={outcome.path} />
    <dl>
      <div><dt>Anchor close</dt><dd>${number(item.anchor_close, 4)}</dd></div>
      <div><dt>Highest threshold</dt><dd>{outcome.highest_threshold_hit || 0}%</dd></div>
      <div><dt>Sessions to peak</dt><dd>{outcome.sessions_to_peak ?? "—"}</dd></div>
      <div><dt>Worst low</dt><dd>{number(outcome.maximum_drawdown_percent)}%</dd></div>
      <div><dt>Ending return</dt><dd>{number(outcome.ending_return_percent)}%</dd></div>
    </dl>
    <details><summary>Point-in-time factor audit</summary><ul>{(score.factors || []).map((factor) => <li key={factor.id}><div><strong>{factor.label}</strong><span>{factor.available ? `${factor.points}/${factor.max_points}` : "unavailable"}</span></div><p>{factor.detail}</p></li>)}</ul></details>
    <footer><span>Features end {date(item.feature_window_end)} · outcome begins {date(item.outcome_window_start)}</span><div><button className="ghost-btn" type="button" onClick={() => onStressExecution?.({ symbol, reference_price: item.anchor_close, daily_volume: item.anchor_average_daily_volume_20 })}>Stress this close</button><button className="ghost-btn" type="button" onClick={() => onOpenTicker?.(symbol)}>Open current research</button></div></footer>
  </article>;
}

function SplitCard({ label, metrics }) {
  return <div><span>{label}</span><strong>{number(metrics?.flagged_hit_frequency_percent)}%</strong><small>flagged observations reaching +20%</small><p>{number(metrics?.flagged_twenty_percent_outcomes)} hits / {number(metrics?.flagged_observations)} flagged · {number(metrics?.missed_twenty_percent_outcomes)} misses</p></div>;
}

export default function ExtremeMoveReplayPanel({ initialTicker = "AAPL", onOpenTicker, onStressExecution }) {
  const [config, setConfig] = useState({ ...DEFAULT_CONFIG, ticker: initialTicker || "AAPL" });
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [exampleSet, setExampleSet] = useState("extreme");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadHistory() {
    try {
      const payload = await getExtremeMoveReplayHistory(20);
      setHistory(payload.replays || []);
    } catch (loadError) {
      setError(loadError.message);
    }
  }

  useEffect(() => { loadHistory(); }, []);
  useEffect(() => {
    if (initialTicker) setConfig((current) => ({ ...current, ticker: initialTicker }));
  }, [initialTicker]);

  function update(event) {
    const { name, value } = event.target;
    setConfig((current) => ({ ...current, [name]: value }));
  }

  async function runReplay(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const next = await runExtremeMoveReplay({
        ...config,
        ticker: String(config.ticker).trim().toUpperCase(),
        forward_sessions: Number(config.forward_sessions),
        stride_sessions: Number(config.stride_sessions),
        minimum_score: Number(config.minimum_score),
      });
      setResult(next);
      setExampleSet("extreme");
      await loadHistory();
    } catch (runError) {
      setError(runError.message);
    } finally {
      setLoading(false);
    }
  }

  async function restore(replayId) {
    setLoading(true);
    setError("");
    try {
      const next = await getExtremeMoveReplay(replayId);
      setResult(next);
      setConfig((current) => ({ ...current, ticker: next.symbol, ...next.parameters }));
    } catch (restoreError) {
      setError(restoreError.message);
    } finally {
      setLoading(false);
    }
  }

  async function clearHistory() {
    if (!globalThis.confirm?.("Clear saved Replay Lab runs? This does not alter Move Lab scans or public-event evidence.")) return;
    try {
      await deleteExtremeMoveReplayHistory();
      setHistory([]);
      setResult(null);
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  const examples = exampleSet === "extreme"
    ? result?.extreme_examples
    : exampleSet === "false"
      ? result?.false_positive_examples
      : result?.missed_extreme_examples;

  return <section className="replay-lab-workspace">
    <div className="card replay-intro">
      <div className="move-lab-title"><div><FlaskConical size={22} /><span>Extreme-Mover Replay Lab · v1</span><h2>Test what Orion could have known before the move</h2></div><span className="research-only-badge">DESCRIPTIVE RESEARCH ONLY</span></div>
      <p>Each replay freezes five price/volume features at a historical decision close, then opens a separate forward window to observe whether price touched +20%, +50% or +100%. Today’s profile, news, filings and fundamentals are excluded to prevent obvious look-ahead leakage.</p>
      <div className="replay-contract-grid">
        <div><ShieldCheck size={16} /><span>Leakage boundary</span><strong>Feature cutoff enforced</strong><small>Future bars never enter the score</small></div>
        <div><Target size={16} /><span>Outcome labels</span><strong>20% · 50% · 100%</strong><small>Observed highs, not executable fills</small></div>
        <div><TrendingUp size={16} /><span>Probability</span><strong>Not calibrated</strong><small>Frequencies are descriptive only</small></div>
      </div>
    </div>

    <form className="card replay-controls" onSubmit={runReplay}>
      <div className="section-heading"><div><h3>Historical replay configuration</h3><p>Start with five years and a 20-session outcome window. Shorter strides add overlapping observations; they do not create independent evidence.</p></div><button className="primary" type="submit" disabled={loading}><RefreshCw size={16} className={loading ? "spin" : ""} />{loading ? "Replaying…" : "Run point-in-time replay"}</button></div>
      <div>
        <label>Ticker<input name="ticker" value={config.ticker} onChange={update} maxLength={15} /></label>
        <label>History<select name="period" value={config.period} onChange={update}><option value="1y">1 year</option><option value="2y">2 years</option><option value="5y">5 years</option></select></label>
        <label>Outcome window<select name="forward_sessions" value={config.forward_sessions} onChange={update}><option value="10">10 sessions</option><option value="20">20 sessions</option><option value="30">30 sessions</option><option value="60">60 sessions</option></select></label>
        <label>Anchor stride<select name="stride_sessions" value={config.stride_sessions} onChange={update}><option value="5">Every 5 sessions</option><option value="10">Every 10 sessions</option><option value="20">Every 20 sessions</option></select></label>
        <label>Flag score<input name="minimum_score" type="number" min="0" max="100" value={config.minimum_score} onChange={update} /></label>
      </div>
      {error && <div className="error">{error}</div>}
    </form>

    {result && <>
      <div className="card replay-summary">
        <div className="section-heading"><div><h3>{result.symbol} replay summary</h3><p>{date(result.sample?.first_feature_date)} to {date(result.sample?.last_feature_date)} · {number(result.sample?.usable_daily_bars)} usable daily bars</p></div><span className="unvalidated-badge">NOT A FORECAST</span></div>
        <div className="replay-metrics">
          <div><span>Observations</span><strong>{number(result.summary?.observations)}</strong><small>{number(result.summary?.flagged_observations)} at/above flag score</small></div>
          {[20, 50, 100].map((threshold) => <div key={threshold}><span>+{threshold}% outcomes</span><strong>{number(result.summary?.threshold_hit_counts?.[String(threshold)])}</strong><small>within {result.parameters?.forward_sessions} sessions</small></div>)}
          <div><span>Best observed high</span><strong>+{number(result.summary?.highest_observed_gain_percent)}%</strong><small>Not an executable return</small></div>
        </div>
        <div className="replay-split"><SplitCard label="Earlier 70% development segment" metrics={result.date_split?.development} /><SplitCard label="Later 30% holdout segment" metrics={result.date_split?.holdout} /></div>
        <p className="replay-warning"><AlertTriangle size={15} />The fixed rules are not fitted on either segment. This split exposes time decay, but it is not sufficient validation and does not remove overlapping-window or survivorship bias.</p>
      </div>

      <div className="card replay-calibration">
        <div className="section-heading"><div><h3>Score-band outcome audit</h3><p>These are historical counts and frequencies, not predicted probabilities.</p></div></div>
        <div className="replay-table"><div className="replay-table-head"><span>Score band</span><span>Samples</span><span>+20%</span><span>+50%</span><span>+100%</span><span>Median high</span><span>Median low</span></div>{(result.score_bands || []).map((band) => <div key={band.label}><strong>{band.label}</strong><span>{number(band.observations)}</span><span>{number(band.descriptive_hit_frequencies_percent?.["20"])}%</span><span>{number(band.descriptive_hit_frequencies_percent?.["50"])}%</span><span>{number(band.descriptive_hit_frequencies_percent?.["100"])}%</span><span>{number(band.median_maximum_gain_percent)}%</span><span>{number(band.median_maximum_drawdown_percent)}%</span></div>)}</div>
      </div>

      <div className="card replay-examples">
        <div className="section-heading"><div><h3>Replay examples</h3><p>Extreme events are de-duplicated into non-overlapping examples. False positives and misses remain visible.</p></div><div className="replay-example-tabs"><button type="button" className={exampleSet === "extreme" ? "active" : ""} onClick={() => setExampleSet("extreme")}>Extreme moves</button><button type="button" className={exampleSet === "false" ? "active" : ""} onClick={() => setExampleSet("false")}>False positives</button><button type="button" className={exampleSet === "missed" ? "active" : ""} onClick={() => setExampleSet("missed")}>Missed moves</button></div></div>
        <div className="replay-example-list">{(examples || []).map((item) => <ReplayExample key={`${item.anchor_date}:${exampleSet}`} item={item} symbol={result.symbol} onOpenTicker={onOpenTicker} onStressExecution={onStressExecution} />)}</div>
        {!examples?.length && <p className="empty-state">No examples matched this category in the selected sample.</p>}
      </div>

      <details className="card replay-observations"><summary>Inspect all {result.observations?.length || 0} sampled decision closes</summary><div>{(result.observations || []).map((item) => <div key={item.anchor_date}><span>{date(item.anchor_date)}</span><strong>{item.preparation_score?.score}/100</strong><span>Max +{number(item.outcome?.maximum_gain_percent)}%</span><span>Low {number(item.outcome?.maximum_drawdown_percent)}%</span><span>{item.outcome?.highest_threshold_hit || 0}% tier</span></div>)}</div></details>

      <div className="card replay-limitations"><h3><AlertTriangle size={17} /> What this replay still cannot prove</h3><ul>{(result.limitations || []).map((item) => <li key={item}>{item}</li>)}</ul><footer><ShieldCheck size={14} />{result.safety_boundary}</footer></div>
    </>}

    <div className="card replay-history">
      <div className="section-heading"><div><h3><Clock3 size={17} /> Replay history</h3><p>Full audits are stored per user. The list loads summaries first to keep the workspace responsive.</p></div><button className="ghost-btn danger-btn" type="button" onClick={clearHistory} disabled={!history.length}><Eraser size={15} /> Clear replays</button></div>
      <div>{history.map((item) => <button type="button" className={item.history_id === result?.history_id ? "active" : ""} key={item.history_id} onClick={() => restore(item.history_id)}><strong>{item.symbol} · {date(item.saved_at)}</strong><span>{item.parameters?.period} · {item.parameters?.forward_sessions} sessions · {number(item.summary?.observations)} observations</span></button>)}</div>
      {!history.length && <p className="empty-state">No saved replays yet.</p>}
    </div>
  </section>;
}
