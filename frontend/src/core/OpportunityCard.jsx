import { useEffect, useState } from "react";
import { ArrowUpRight, BookmarkPlus } from "lucide-react";
import { explainPredictivePrediction, saveCorePlan } from "../api/api";
import useAsyncTask from "./useAsyncTask";
import { currentDecision, finite, localTime, price, priceZone } from "./decisionPresentation";

function marketSessionLabel(result) {
  const mode = String(
    result?.market_session ||
    result?.session_mode ||
    result?.analysis_mode ||
    ""
  ).trim().toLowerCase();

  if (mode === "regular" || mode === "open" || mode === "market_open") {
    return { label: "MARKET OPEN", tone: "open" };
  }

  if (mode === "premarket" || mode === "pre_market") {
    return { label: "PRE-MARKET", tone: "premarket" };
  }

  if (mode === "after_hours" || mode === "afterhours") {
    return { label: "AFTER HOURS", tone: "after-hours" };
  }

  if (mode === "closed" || result?.status === "market_closed") {
    return { label: "MARKET CLOSED", tone: "closed" };
  }

  return { label: "SESSION UNVERIFIED", tone: "unknown" };
}

export default function OpportunityCard({ decision, onAnalyze, onSave, saved = false, now, analysis = false }) {
  const [clock, setClock] = useState(Date.now());
  const explanation = useAsyncTask();
  const monitoring = useAsyncTask();
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 10000); return () => clearInterval(timer); }, []);
  const result = currentDecision(decision, now ?? clock);
  if (!result) return null;
  const evidence = result.evidence?.strategy_analysis;
  const label = analysis ? result.decision : result.direction;
  const marketSession = marketSessionLabel(result);
  return <article className={`opportunity-card ${result.direction.toLowerCase()}`} aria-label={`${result.ticker} analysis`}>
    <header className="opportunity-heading">
      <div><div className="opportunity-symbol"><h2>{result.ticker}</h2><span className={`decision-pill ${result.direction.toLowerCase()}`}>{label}</span></div>
        <p>{result.company_name || "Company name unavailable"}</p></div>
      <div className={`opportunity-confidence opportunity-session ${marketSession.tone}`}>
        <span>Current market session</span>
        <strong>{marketSession.label}</strong>
      </div>
    </header>
    <p className="opportunity-why">{result.actionable ? result.reasons?.[0] : result.warnings?.[0] || result.reasons?.[0]}</p>
    {!result.actionable && evidence?.data_quality?.sufficient && <p className="core-technical-note"><span>Technical context</span>{result.reasons?.[0]}</p>}
    {result.actionable ? <dl className="opportunity-plan">
      <div><dt>Entry zone</dt><dd>{priceZone(result.entry_zone)}</dd></div>
      <div><dt>Invalidation</dt><dd>{price(result.invalidation)}</dd></div>
      <div><dt>Target area</dt><dd>{priceZone(result.targets)}</dd></div>
      <div><dt>Risk / reward</dt><dd>1 : {result.risk_reward}</dd></div>
      <div><dt>Expected return</dt><dd>{finite(result.expected_move) ? `${Number(result.expected_move).toFixed(2)}%` : "Unavailable"}</dd></div>
      <div><dt>Time horizon</dt><dd>{result.timeframe || "Unavailable"}</dd></div>
    </dl> : <p className="withheld-plan">No trade plan issued. Entry, stop and targets are withheld.</p>}
    <div className="opportunity-context"><span>Liquidity {result.liquidity_tier ? `${result.liquidity_tier} · ${result.liquidity_score}/100` : "not verified"}</span>
      <span>{result.market_regime || "Market regime unavailable"}</span></div>
    <footer className="opportunity-footer">
      <details className="decision-details"><summary>Details</summary>
        <p>Evidence: {localTime(result.timestamp)} · {result.status.replaceAll("_", " ")}</p>
        {result.reasons?.map((reason, i) => <p key={i}>{reason}</p>)}
        {result.warnings?.length > 0 && <ul>{result.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}
        {result.confidence_unavailable_reasons?.map((reason, i) => <p key={`confidence-${i}`}>Directional confidence unavailable: {reason}</p>)}
        {result.preparation && <p>Preparation: {result.preparation.preparation || "current baseline reused"}. {result.preparation.message}</p>}
        {result.decision_id && <p>Final decision saved to your private history. Later checks do not rewrite this evidence.</p>}
        <p>{result.semantics}</p>
        {evidence?.strategies?.length > 0 && <div className="core-evidence-list"><h3>Technical evidence</h3>{evidence.strategies.map(strategy => <div key={strategy.id}>
          <strong>{strategy.name}</strong><span>{strategy.status?.replaceAll("_", " ")}</span><p>{strategy.summary}</p>
        </div>)}</div>}
        {result.model_outputs?.strategy_consensus && <p>Strategy agreement: {result.model_outputs.strategy_consensus.agreement_score ?? "Unavailable"}/100. This is not a probability.</p>}
        {result.prediction_id && result.actionable && <div className="core-ai-explanation">
          <button className="core-text-button" type="button" disabled={explanation.busy} onClick={() => explanation.run(() => explainPredictivePrediction(result.prediction_id))}>{explanation.busy ? "Orion is explaining…" : "Explain with Orion"}</button>
          {explanation.error && <p role="alert">{explanation.error}</p>}
          {explanation.data?.explanation && <><p>{explanation.data.explanation.summary}</p><p>{explanation.data.explanation.market_context}</p></>}
        </div>}
        <details className="core-raw"><summary>Source evidence and model outputs</summary><pre>{JSON.stringify({ evidence: result.evidence, model_outputs: result.model_outputs }, null, 2)}</pre></details>
      </details>
      <div className="opportunity-actions">
        {result.actionable && result.decision_id && <button type="button" className="core-text-button" disabled={monitoring.busy || Boolean(monitoring.data)} onClick={() => monitoring.run(() => saveCorePlan(result.decision_id))}>{monitoring.data ? "Plan saved" : monitoring.busy ? "Saving…" : "Save plan to monitor"}</button>}
        {onSave && <button type="button" className="core-text-button" disabled={saved} onClick={() => onSave(result.ticker)}><BookmarkPlus size={15} />{saved ? "Saved" : "Save stock"}</button>}
        {onAnalyze && <button type="button" className="core-text-button" onClick={() => onAnalyze(result.ticker)}>Analyze <ArrowUpRight size={15} /></button>}
      </div>
    </footer>
    {monitoring.error && <p role="alert" className="core-warning">{monitoring.error}</p>}
  </article>;
}
