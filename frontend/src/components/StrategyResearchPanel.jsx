import React, { useEffect, useMemo, useState } from "react";
import {
  Check, CircleAlert, CircleX, FlaskConical, GitCompareArrows,
  MessageCircle, RefreshCw, ShieldCheck, TrendingUp,
} from "lucide-react";
import { getStrategyResearch } from "../api/api";

const STATUS_LABELS = {
  triggered: "Rules matched",
  aligned: "Trend aligned",
  forming: "Forming",
  not_aligned: "Not aligned",
  data_insufficient: "Data insufficient",
  peer_required: "Peer required",
  divergence_screen: "Divergence screen",
  portfolio_required: "Portfolio review",
  defensive_trigger: "Defensive cross",
  defensive: "Defensive warning",
};

function formatValue(value) {
  if (value == null) return "—";
  return typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(value);
}

function statusClass(status) {
  if (["triggered", "divergence_screen"].includes(status)) return "matched";
  if (["aligned", "forming"].includes(status)) return "watch";
  if (["defensive", "defensive_trigger"].includes(status)) return "defensive";
  return "quiet";
}

function RuleCheck({ check }) {
  const Icon = !check.available ? CircleAlert : check.passed ? Check : CircleX;
  return (
    <li className={!check.available ? "unavailable" : check.passed ? "passed" : "failed"}>
      <Icon size={16} aria-hidden="true" />
      <span><strong>{check.name.replaceAll("_", " ")}</strong><small>{check.detail}</small></span>
    </li>
  );
}

export default function StrategyResearchPanel({ ticker, onAskOrion, onOpenBacktests, initialData = null }) {
  const [research, setResearch] = useState(initialData);
  const [loading, setLoading] = useState(!initialData);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState(initialData?.strategy_analysis?.top_setup?.id || "trend_pullback");
  const [peerDraft, setPeerDraft] = useState(initialData?.peer || "");
  const [peer, setPeer] = useState(initialData?.peer || "");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    getStrategyResearch(ticker, peer)
      .then((next) => {
        if (!active) return;
        setResearch(next);
        const strategies = next?.strategy_analysis?.strategies || [];
        const preferred = next?.strategy_analysis?.top_setup?.id;
        setSelectedId((current) => strategies.some((item) => item.id === current) ? current : preferred || strategies[0]?.id || "trend_pullback");
      })
      .catch((requestError) => { if (active) setError(requestError.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [ticker, peer, refreshKey]);

  const analysis = research?.strategy_analysis;
  const strategies = analysis?.strategies || [];
  const selected = useMemo(
    () => strategies.find((item) => item.id === selectedId) || strategies[0],
    [strategies, selectedId]
  );
  const levels = selected?.levels || {};
  const hasLevels = [levels.entry, levels.stop, levels.target].some((value) => value != null);

  function comparePeer(event) {
    event.preventDefault();
    const clean = peerDraft.trim().toUpperCase();
    if (clean === String(ticker).toUpperCase()) {
      setError("Pair ticker must differ from the selected ticker");
      return;
    }
    setPeer(clean);
    setSelectedId("pairs_trading");
  }

  return (
    <section className="card strategy-research-card">
      <div className="strategy-research-heading">
        <div>
          <div className="card-title"><FlaskConical size={20} /> Deterministic Strategy Lab</div>
          <h2>{ticker} setup research</h2>
          <p>Each score is the percentage of required written rules currently satisfied. Unavailable evidence cannot pass, and the score is not a probability of profit.</p>
        </div>
        <div className="strategy-research-actions">
          <button className="ghost-btn" type="button" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}><RefreshCw size={15} /> {loading ? "Refreshing…" : "Refresh"}</button>
          <button className="ghost-btn" type="button" onClick={onOpenBacktests}><TrendingUp size={15} /> Backtest</button>
          <button className="primary-btn" type="button" onClick={onAskOrion}><MessageCircle size={15} /> Ask Orion</button>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}
      {research?.data_quality?.partial_failure && <p className="warning-text">Some provider data is stale or unavailable. Missing rules remain unconfirmed.</p>}
      {analysis?.top_setup ? (
        <div className="strategy-top-setup">
          <ShieldCheck size={20} />
          <div><span>Highest current rule match</span><strong>{analysis.top_setup.name} · {analysis.top_setup.score ?? "—"}/100</strong><small>{analysis.top_setup.summary}</small></div>
          <em>Research only</em>
        </div>
      ) : analysis && (
        <div className="strategy-top-setup neutral">
          <CircleAlert size={20} />
          <div><span>No qualified long setup</span><strong>Wait for the written rules</strong><small>Orion is not relaxing thresholds to manufacture a recommendation.</small></div>
        </div>
      )}

      {loading && !analysis ? <div className="strategy-loading"><span className="pulse-dot" /> Loading two-year, intraday and benchmark evidence…</div> : <>
        <div className="strategy-selector" role="tablist" aria-label="Trading strategies">
          {strategies.map((strategy) => (
            <button
              key={strategy.id}
              type="button"
              role="tab"
              aria-selected={strategy.id === selected?.id}
              className={strategy.id === selected?.id ? "active" : ""}
              onClick={() => setSelectedId(strategy.id)}
            >
              <span>{strategy.rank}</span>
              <strong>{strategy.name}</strong>
              <small>{strategy.score == null ? "—" : `${strategy.score}/100`} · {STATUS_LABELS[strategy.status] || strategy.status}</small>
            </button>
          ))}
        </div>

        {selected && <div className="strategy-detail">
          <header>
            <div><span>{selected.category} · {selected.timeframe}</span><h3>{selected.name}</h3><p>{selected.summary}</p></div>
            <div className={`strategy-score ${statusClass(selected.status)}`}><strong>{selected.score ?? "—"}</strong><span>rule completion</span><small>{STATUS_LABELS[selected.status] || selected.status}</small></div>
          </header>

          <div className="strategy-playbook-grid">
            <div><span>Evidence context</span><p>{selected.evidence}</p></div>
            <div><span>Setup</span><p>{selected.setup}</p></div>
            <div><span>Entry trigger</span><p>{selected.trigger}</p></div>
            <div><span>Exit framework</span><p>{selected.exit}</p></div>
          </div>

          {selected.id === "pairs_trading" && <form className="pair-research-form" onSubmit={comparePeer}>
            <GitCompareArrows size={18} />
            <label>Related peer ticker<input value={peerDraft} maxLength={15} placeholder="e.g. GOOGL" onChange={(event) => setPeerDraft(event.target.value.toUpperCase())} /></label>
            <button className="ghost-btn" type="submit">Run pair screen</button>
            {peer && <small>Screening {ticker} against {peer}; correlation and z-score do not prove cointegration.</small>}
          </form>}

          <div className="strategy-evidence-layout">
            <div>
              <h4>Rule checklist</h4>
              <ul className="strategy-checks">{selected.checks.map((check) => <RuleCheck check={check} key={check.name} />)}</ul>
            </div>
            <aside>
              <h4>Research levels</h4>
              {hasLevels ? <div className="strategy-levels">
                <div><span>Entry trigger</span><strong>{formatValue(levels.entry)}</strong></div>
                <div><span>Invalidation stop</span><strong>{formatValue(levels.stop)}</strong></div>
                <div><span>2R / research target</span><strong>{formatValue(levels.target)}</strong></div>
                <div><span>Planned reward/risk</span><strong>{levels.risk_reward == null ? "—" : `${formatValue(levels.risk_reward)}:1`}</strong></div>
              </div> : <p className="muted-text">No defensible price plan is available until the prerequisite setup and data requirements are met.</p>}
              {Object.keys(selected.evidence_snapshot || {}).length > 0 && <details><summary>Evidence snapshot</summary><dl>{Object.entries(selected.evidence_snapshot).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(" · ") || "—" : formatValue(value)}</dd></div>)}</dl></details>}
            </aside>
          </div>

          {(selected.risk_notes.length > 0 || selected.limitations.length > 0) && <div className="strategy-caveats">
            <CircleAlert size={18} />
            <div><strong>Risk and limitations</strong>{[...selected.risk_notes, ...selected.limitations].map((note) => <p key={note}>{note}</p>)}</div>
          </div>}
        </div>}
      </>}

      <footer className="strategy-safety-note"><ShieldCheck size={16} /> “Rules matched” describes this data snapshot. It is not certainty, financial advice or permission to place an order; validate freshness, costs, sizing and the thesis first.</footer>
    </section>
  );
}
