import React, { useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, Clock3, Database, Eraser, Radar, RefreshCw, ShieldCheck, Square, Wifi, WifiOff, Zap } from "lucide-react";
import {
  deleteExplosiveMoveHistory,
  getExplosiveMoveHistory,
  getExplosiveMoveStatus,
  getExplosiveMoveStreamEvents,
  getExplosiveMoveStreamStatus,
  scanExplosiveMoves,
  startExplosiveMoveStream,
  stopExplosiveMoveStream,
} from "../api/api";

const DEFAULT_FILTERS = {
  universe_source: "auto",
  minimum_price: 0.5,
  minimum_market_cap: 0,
  minimum_float: 0,
  minimum_average_dollar_volume: 1000000,
  maximum_spread_percent: 2,
  minimum_days_since_ipo: 0,
  danger_threshold: 65,
};

function displayNumber(value, maximumFractionDigits = 0) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits });
}

function displayTime(value) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function title(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

function displayAge(value) {
  if (value == null || Number.isNaN(Number(value))) return "No data yet";
  if (Number(value) < 1) return "Just now";
  return `${displayNumber(value, 0)}s ago`;
}

function ScoreCard({ kind, score }) {
  const details = kind === "danger" ? score?.risks : score?.factors;
  const pointKey = kind === "danger" ? "risk_points" : "points";
  return <section className={`move-score move-score-${kind}`}>
    <div className="move-score-heading">
      <span>{kind === "pre" ? "PreMoveScore" : kind === "ignition" ? "IgnitionScore" : "DangerScore"}</span>
      <strong>{score?.score ?? "—"}<small>/100</small></strong>
    </div>
    <p>{score?.score_meaning || "Evidence unavailable."}</p>
    <div className="move-score-coverage"><span style={{ width: `${Math.min(100, score?.evidence_coverage_percent || 0)}%` }} /></div>
    <small>{score?.evidence_coverage_percent || 0}% evidence coverage{score?.state ? ` · ${title(score.state)}` : score?.level ? ` · ${title(score.level)}` : ""}</small>
    <details>
      <summary>Audit {details?.length || 0} inputs</summary>
      <ul>{(details || []).map((factor) => <li key={factor.id}>
        <strong>{factor.label}</strong><span>{factor.available ? `${factor[pointKey] || 0}/${factor.max_points}` : "unavailable"}</span>
        <p>{factor.explanation}</p>
      </li>)}</ul>
    </details>
  </section>;
}

function EventList({ events }) {
  if (!events?.length) return <p className="empty-state">No normalized public events were returned for this candidate.</p>;
  return <div className="move-events">{events.slice(0, 6).map((event) => <article key={`${event.source}:${event.source_id}`}>
    <div><strong>{event.headline || title(event.classification)}</strong><span>{event.source} · {displayTime(event.published_at)}</span></div>
    <p>{event.explanation}</p>
    <footer>
      <span>{title(event.classification)}</span><span>{title(event.sentiment)}</span><span>{title(event.materiality)} materiality</span>
      {event.reaction_latency_seconds != null && <span>{displayNumber(event.reaction_latency_seconds)}s reaction latency</span>}
      {event.url && <a href={event.url} target="_blank" rel="noreferrer">Source</a>}
    </footer>
  </article>)}</div>;
}

function CandidateCard({ candidate, onOpenTicker }) {
  const risk = candidate.adaptive_risk || {};
  return <article className={`card move-candidate decision-${String(candidate.decision).toLowerCase()}`}>
    <header className="move-candidate-heading">
      <div><span>{title(candidate.category?.primary)}</span><h3>{candidate.symbol}</h3>{candidate.stream_evidence?.status === "fresh" && <small className="live-evidence-badge"><Wifi size={11} /> Live evidence</small>}</div>
      <div><strong>{title(candidate.decision)}</strong><small>research state—not an instruction</small></div>
    </header>
    <div className="move-score-grid">
      <ScoreCard kind="pre" score={candidate.pre_move_score} />
      <ScoreCard kind="ignition" score={candidate.ignition_score} />
      <ScoreCard kind="danger" score={candidate.danger_score} />
    </div>
    {candidate.blockers?.length > 0 && <div className="move-blockers"><AlertTriangle size={16} /><div><strong>No-trade gates</strong><ul>{candidate.blockers.map((item) => <li key={item}>{item}</li>)}</ul></div></div>}
    <section className="adaptive-risk-card">
      <div><ShieldCheck size={18} /><span>Adaptive risk budget</span><strong>{title(risk.status)}</strong></div>
      <dl>
        <div><dt>Research size</dt><dd>{risk.shares ?? 0} shares · ${displayNumber(risk.recommended_position_value, 2)}</dd></div>
        <div><dt>Planned account risk</dt><dd>{risk.risk_per_trade_percent == null ? "—" : `${displayNumber(risk.risk_per_trade_percent, 3)}%`}</dd></div>
        <div><dt>Realistic stop</dt><dd>{risk.realistic_stop == null ? "—" : `$${displayNumber(risk.realistic_stop, 4)}`}</dd></div>
        <div><dt>Leverage ceiling</dt><dd>{displayNumber(risk.maximum_permitted_leverage, 1)}× · borrowed exposure disabled</dd></div>
        <div><dt>Slippage assumption</dt><dd>{displayNumber(risk.estimated_slippage_percent, 3)}%</dd></div>
        <div><dt>Gap-loss stress</dt><dd>${displayNumber(risk.catastrophic_gap_loss_estimate, 2)}</dd></div>
      </dl>
      {risk.blockers?.length > 0 && <p>{risk.blockers.join(" · ")}</p>}
    </section>
    <details className="move-event-details"><summary>Public catalyst and filing evidence ({candidate.events?.length || 0})</summary><EventList events={candidate.events} /></details>
    <footer className="move-candidate-footer">
      <div>{(candidate.category?.tags || []).map((tag) => <span key={tag}>{title(tag)}</span>)}</div>
      <button className="ghost-btn" type="button" onClick={() => onOpenTicker?.(candidate.symbol)}>Open research</button>
    </footer>
  </article>;
}

export default function ExplosiveMovePanel({ alpacaConnected, trading212Connected, activeSource, onOpenTicker, onOpenBroker }) {
  const [status, setStatus] = useState(null);
  const [streamStatus, setStreamStatus] = useState(null);
  const [streamEvents, setStreamEvents] = useState([]);
  const [streamFeed, setStreamFeed] = useState("iex");
  const [streamBusy, setStreamBusy] = useState(false);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const streamCursor = useRef(0);
  const anyBroker = alpacaConnected || trading212Connected;
  const candidateSymbols = (result?.candidates || []).slice(0, 16).map((candidate) => candidate.symbol);
  const streamRunning = Boolean(streamStatus?.running);

  async function loadFoundation() {
    try {
      const [nextStatus, saved] = await Promise.all([getExplosiveMoveStatus(), getExplosiveMoveHistory(20)]);
      setStatus(nextStatus);
      setStreamStatus(nextStatus.market_feed?.stream || null);
      setHistory(saved.scans || []);
      setResult((current) => current || saved.scans?.[0] || null);
    } catch (loadError) {
      setError(loadError.message);
    }
  }

  useEffect(() => { loadFoundation(); }, []);

  useEffect(() => {
    if (!streamRunning) return undefined;
    let active = true;
    async function pollStream() {
      try {
        const [nextStatus, page] = await Promise.all([
          getExplosiveMoveStreamStatus(),
          getExplosiveMoveStreamEvents(streamCursor.current, 100),
        ]);
        if (!active) return;
        setStreamStatus(nextStatus);
        if (page.reset_required) setStreamEvents(page.events || []);
        else if (page.events?.length) {
          setStreamEvents((current) => [...current, ...page.events].slice(-60));
        }
        streamCursor.current = page.next_sequence || streamCursor.current;
      } catch (pollError) {
        if (active) setError(`Live evidence status: ${pollError.message}`);
      }
    }
    pollStream();
    const timer = globalThis.setInterval(pollStream, 2500);
    return () => { active = false; globalThis.clearInterval(timer); };
  }, [streamRunning]);

  function updateFilter(event) {
    const { name, value } = event.target;
    setFilters((current) => ({ ...current, [name]: value }));
  }

  async function scan() {
    setLoading(true);
    setError("");
    try {
      const next = await scanExplosiveMoves(filters);
      setResult(next);
      if (next.feed_status?.stream) setStreamStatus(next.feed_status.stream);
      setHistory((current) => [next, ...current.filter((item) => item.history_id !== next.history_id)].slice(0, 20));
    } catch (scanError) {
      setError(scanError.message);
    } finally {
      setLoading(false);
    }
  }

  async function startStream() {
    if (!candidateSymbols.length) {
      setError("Run an evidence scan first so Orion has a bounded symbol set to stream.");
      return;
    }
    setStreamBusy(true);
    setError("");
    try {
      const response = await startExplosiveMoveStream(candidateSymbols, streamFeed, false);
      setStreamStatus(response.stream);
      setStreamEvents([]);
      streamCursor.current = 0;
    } catch (streamError) {
      setError(streamError.message);
    } finally {
      setStreamBusy(false);
    }
  }

  async function stopStream() {
    setStreamBusy(true);
    setError("");
    try {
      const response = await stopExplosiveMoveStream();
      setStreamStatus(response.stream);
    } catch (streamError) {
      setError(streamError.message);
    } finally {
      setStreamBusy(false);
    }
  }

  async function clearHistory() {
    if (!globalThis.confirm?.("Clear saved Move Lab scans? The normalized public-event audit will be preserved.")) return;
    try {
      await deleteExplosiveMoveHistory();
      setHistory([]);
      setResult(null);
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  return <section className="move-lab-workspace">
    <div className="card move-lab-intro">
      <div className="move-lab-title"><div><Radar size={22} /><span>Explosive-move intelligence · foundation</span><h2>Find preparation, confirm ignition, reject danger</h2></div><span className="research-only-badge">RESEARCH / SHADOW ONLY</span></div>
      <p>Orion keeps three questions separate. PreMoveScore measures observable preparation, IgnitionScore measures an active move, and DangerScore measures dilution, distress, liquidity and execution risk. None is a probability or a buy signal.</p>
      <div className="move-feed-grid">
        <div><Activity size={16} /><span>Market feed</span><strong>{title(streamRunning ? `alpaca ${streamStatus?.feed}` : status?.market_feed?.current_mode || "checking")}</strong><small>{streamRunning ? `${streamStatus?.symbol_count || 0} symbols · ${title(streamStatus?.state)}` : "WebSocket not active"}</small></div>
        <div><Database size={16} /><span>SEC EDGAR</span><strong>{status?.sec_edgar?.configured ? "Configured" : "Not configured"}</strong><small>Filing metadata gate</small></div>
        <div><ShieldCheck size={16} /><span>Probability model</span><strong>Not calibrated</strong><small>No probability targets shown</small></div>
        <div><Zap size={16} /><span>Execution</span><strong>No order route</strong><small>Adaptive risk is research-only</small></div>
      </div>
      {!anyBroker && <div className="opportunity-blocked"><AlertTriangle size={17} />Connect Alpaca Paper or Trading 212 Demo to scan its tradable universe.<button className="ghost-btn" type="button" onClick={onOpenBroker}>Open Paper Lab</button></div>}
    </div>

    <div className={`card move-stream-panel stream-${streamStatus?.state || "stopped"}`}>
      <div className="section-heading">
        <div><h3>{streamRunning ? <Wifi size={17} /> : <WifiOff size={17} />} Live Alpaca evidence</h3><p>Explicitly opens one market-data and one news connection for the latest bounded candidate set. Market observations stay in memory; normalized public news joins your per-user audit.</p></div>
        <div className="move-stream-actions">
          <label>Feed<select value={streamFeed} onChange={(event) => setStreamFeed(event.target.value)} disabled={streamRunning || streamBusy}><option value="iex">IEX</option><option value="sip">SIP · entitlement required</option><option value="delayed_sip">Delayed SIP</option></select></label>
          {streamRunning
            ? <button className="ghost-btn danger-btn" type="button" onClick={stopStream} disabled={streamBusy}><Square size={14} />{streamBusy ? "Stopping…" : "Stop stream"}</button>
            : <button className="primary" type="button" onClick={startStream} disabled={streamBusy || !alpacaConnected || !candidateSymbols.length}><Wifi size={15} />{streamBusy ? "Starting…" : "Start live evidence"}</button>}
        </div>
      </div>
      {!alpacaConnected && <div className="move-stream-note"><AlertTriangle size={15} />Live evidence requires the Alpaca Paper connection. Trading 212 scans continue with bounded snapshots.</div>}
      {alpacaConnected && !candidateSymbols.length && <div className="move-stream-note">Run one bounded scan first. Its top candidates become the initial subscription; later scans update the active symbol set.</div>}
      <div className="move-channel-grid">
        {["market", "news"].map((channel) => {
          const detail = streamStatus?.channels?.[channel] || {};
          return <div key={channel}><span>{channel} channel</span><strong>{title(detail.state || "stopped")}</strong><small>Last data: {displayAge(detail.last_data_age_seconds)} · {detail.reconnects || 0} reconnects</small>{detail.last_error && <p>{detail.last_error}</p>}</div>;
        })}
        <div><span>Buffer</span><strong>Sequence {streamStatus?.latest_sequence || 0}</strong><small>{streamStatus?.dropped_events || 0} dropped · bounded memory</small></div>
      </div>
      <details className="move-live-tape" open={streamRunning}>
        <summary>Live evidence tape ({streamEvents.length})</summary>
        <div>{streamEvents.slice().reverse().map((event) => <article key={event.sequence} className={`event-${event.type}`}><span>{event.sequence} · {title(event.type)}</span><strong>{event.symbol || event.data?.symbols?.join(", ") || title(event.channel)}</strong><p>{event.data?.headline || event.data?.message || (event.type === "bar" ? `Close $${displayNumber(event.data?.close, 4)} · volume ${displayNumber(event.data?.volume)}` : "Subscription state updated")}</p><time>{displayTime(event.received_at)}</time></article>)}</div>
        {!streamEvents.length && <p className="empty-state">No streamed bars, news or connection events have arrived yet.</p>}
      </details>
      <footer><ShieldCheck size={14} />Research evidence only. No streamed event can submit, prepare or approve an order.</footer>
    </div>

    <div className="card move-controls">
      <div className="section-heading"><div><h3>Bounded rotating universe scan</h3><p>Every run advances through a broker-provided universe batch; it does not claim one-request coverage of every listed security.</p></div><button className="primary" type="button" onClick={scan} disabled={loading || !anyBroker}><RefreshCw size={16} className={loading ? "spin" : ""} />{loading ? "Scanning evidence…" : "Run evidence scan"}</button></div>
      <div className="move-filter-grid">
        <label>Tradable universe<select name="universe_source" value={filters.universe_source} onChange={updateFilter}><option value="auto">Automatic · {activeSource || "active broker"}</option><option value="alpaca">Alpaca Paper</option><option value="trading212_demo">Trading 212 Demo</option></select></label>
        <label>Minimum price<input name="minimum_price" type="number" min="0.01" step="0.01" value={filters.minimum_price} onChange={updateFilter} /></label>
        <label>Minimum market cap<input name="minimum_market_cap" type="number" min="0" step="1000000" value={filters.minimum_market_cap} onChange={updateFilter} /></label>
        <label>Minimum float<input name="minimum_float" type="number" min="0" step="100000" value={filters.minimum_float} onChange={updateFilter} /></label>
        <label>Minimum daily $ volume<input name="minimum_average_dollar_volume" type="number" min="0" step="100000" value={filters.minimum_average_dollar_volume} onChange={updateFilter} /></label>
        <label>Maximum spread %<input name="maximum_spread_percent" type="number" min="0.01" max="10" step="0.05" value={filters.maximum_spread_percent} onChange={updateFilter} /></label>
        <label>Minimum IPO age (days)<input name="minimum_days_since_ipo" type="number" min="0" value={filters.minimum_days_since_ipo} onChange={updateFilter} /></label>
        <label>Danger rejection threshold<input name="danger_threshold" type="number" min="25" max="100" value={filters.danger_threshold} onChange={updateFilter} /></label>
      </div>
      {error && <div className="error">{error}</div>}
    </div>

    {result && <div className="move-results">
      <div className="card move-scan-summary">
        <div><Radar size={18} /><strong>{result.candidates?.length || 0} assessments</strong><span>{displayNumber(result.discovery?.screened)} screened · {displayNumber(result.discovery?.provider_universe_size)} provider instruments</span></div>
        <p>{result.safety_boundary}</p>
        <div className="move-coverage-note"><strong>Coverage contract:</strong> {title(result.scanner_contract?.coverage_model)}. Persistent market/news WebSockets: {title(result.feed_status?.persistent_websocket?.state || "stopped")}.</div>
      </div>
      {result.candidates?.length ? <div className="move-candidate-grid">{result.candidates.map((candidate) => <CandidateCard key={candidate.symbol} candidate={candidate} onOpenTicker={onOpenTicker} />)}</div> : <div className="card empty-state">No candidate survived the current market, category, liquidity and data-quality filters. No Trade is a valid result.</div>}
    </div>}

    <div className="card move-history">
      <div className="section-heading"><div><h3><Clock3 size={17} /> Scan history</h3><p>Recommendations remain stable when you move between workspaces. Clearing scans preserves the normalized event audit.</p></div><button className="ghost-btn danger-btn" type="button" onClick={clearHistory} disabled={!history.length}><Eraser size={15} /> Clear scans</button></div>
      <div>{history.map((item) => <button type="button" className={item.history_id === result?.history_id ? "active" : ""} key={item.history_id} onClick={() => setResult(item)}><strong>{displayTime(item.saved_at || item.as_of)}</strong><span>{item.candidates?.length || 0} assessments · {title(item.discovery?.universe_source)}</span></button>)}</div>
      {!history.length && <p className="empty-state">No saved scans yet.</p>}
    </div>
  </section>;
}
