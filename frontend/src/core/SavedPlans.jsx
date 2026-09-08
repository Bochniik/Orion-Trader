import { useEffect, useRef, useState } from "react";
import { getCorePlans, getCoreDecisions, stopCorePlan } from "../api/api";
import useAsyncTask from "./useAsyncTask";
import useCoreJob from "./useCoreJob";
import { localTime } from "./decisionPresentation";

export function PlanRows({ plans = [], onAnalyze, onStop }) {
  if (!plans.length) return <p>No saved plans. A qualified analysis offers “Save plan to monitor”. Saving a stock alone does not create a plan.</p>;
  return <ul className="core-plan-list">{plans.map(plan => <li key={plan.decision_id}>
    <div><button className="core-text-button" type="button" onClick={() => onAnalyze(plan.decision.ticker)}>{plan.decision.ticker}</button><span>{plan.decision.direction} · {plan.decision.timeframe}</span></div>
    <p>{plan.latest_check?.message || "Not checked yet."}</p>
    <small>Last checked: {localTime(plan.latest_check?.checked_at)} · Expires: {localTime(plan.decision.expires_at)}</small>
    {plan.latest_check?.outcome && <p className="core-muted">Fixed-horizon reference return: {plan.latest_check.outcome.reference_return_percent}%. This is not an executed trade.</p>}
    <button className="core-text-button" type="button" onClick={() => onStop(plan.decision_id)}>Stop monitoring</button>
  </li>)}</ul>;
}

export default function SavedPlans({ onAnalyze, dataRevision }) {
  const plans = useAsyncTask(), history = useAsyncTask(), mutation = useAsyncTask();
  const checks = useCoreJob();
  const [monitor, setMonitor] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const busy = useRef(false);
  const refresh = () => plans.run(signal => getCorePlans({ signal }));
  useEffect(() => { refresh(); setMonitor(false); }, [dataRevision]);
  async function check() {
    if (busy.current) return;
    busy.current = true;
    try { const result = await checks.run({ kind: "check_plans", prepare: false }); if (result) await refresh(); }
    finally { busy.current = false; }
  }
  useEffect(() => {
    if (!monitor) return;
    check();
    const timer = setInterval(() => { if (document.visibilityState === "visible") check(); }, 60000);
    return () => clearInterval(timer);
  }, [monitor]);
  async function stop(id) {
    const result = await mutation.run(() => stopCorePlan(id));
    if (result) await refresh();
  }
  function toggleHistory(event) {
    const open = event.currentTarget.open;
    setHistoryOpen(open);
    if (open) history.run(signal => getCoreDecisions({ signal }));
  }
  return <section className="core-monitoring" aria-label="Saved decision plans">
    <h2>Saved plans</h2>
    {plans.error && <p role="alert">{plans.error}</p>}
    {plans.busy && <p role="status">Loading plans…</p>}
    <PlanRows plans={plans.data?.plans} onAnalyze={onAnalyze} onStop={stop} />
    {Boolean(plans.data?.plans?.length) && <div className="core-plan-controls">
      <button className="core-button secondary" type="button" disabled={checks.busy} onClick={check}>Check plans now</button>
      <label><input type="checkbox" checked={monitor} onChange={event => { setMonitor(event.target.checked); if (!event.target.checked) checks.cancel(); }} />Check every minute while this screen is open</label>
    </div>}
    <p className="core-muted">Monitoring is opt-in and pauses when you leave My Stocks or close Orion. Background tabs do not start new checks. Checks may miss moves between observations; target/stop order can be unknown. No orders are placed.</p>
    {checks.busy && <p role="status">{checks.progress} <button type="button" className="core-text-button" onClick={() => { setMonitor(false); checks.cancel(); }}>Cancel check</button></p>}
    {(checks.error || mutation.error) && <p role="alert">{checks.error || mutation.error}</p>}
    <details className="core-decision-history" open={historyOpen} onToggle={toggleHistory}><summary>Recent decision history</summary>
      <p>Original verdicts, including WAIT. These are historical records, not current recommendations.</p>
      {history.busy ? <p role="status">Loading history…</p> : history.error ? <p role="alert">{history.error}</p> : <ul>{(history.data?.decisions || []).map(item => <li key={item.decision_id}><button className="core-text-button" type="button" onClick={() => onAnalyze(item.ticker)}>{item.ticker} · {item.decision}</button><small>{localTime(item.recorded_at)} · {item.origin}</small></li>)}</ul>}
      {!history.busy && history.data?.decisions?.length === 0 && <p>No final decisions saved yet.</p>}
    </details>
  </section>;
}
