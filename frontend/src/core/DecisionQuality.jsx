import { useEffect, useRef } from "react";
import { getCoreQuality } from "../api/api";
import useAsyncTask from "./useAsyncTask";
import useCoreJob from "./useCoreJob";

function percent(value, digits = 1) {
  return value == null ? "Unavailable" : `${(Number(value) * 100).toFixed(digits)}%`;
}

export default function DecisionQuality({ dataRevision }) {
  const quality = useAsyncTask();
  const update = useCoreJob();
  const busy = useRef(false);
  const refresh = () => quality.run(signal => getCoreQuality({ signal }));
  useEffect(() => { refresh(); }, [dataRevision]);
  async function settle() {
    if (busy.current) return;
    busy.current = true;
    try { const result = await update.run({ kind: "check_outcomes", prepare: false }); if (result) refresh(); }
    finally { busy.current = false; }
  }
  const report = quality.data;
  const metrics = report?.forecast_metrics || {};
  return <section className="core-monitoring" aria-label="Decision quality">
    <details>
      <summary>Decision quality · {report?.status === "review_ready" ? "Ready for review" : report?.status === "developing" ? "Still collecting evidence" : "No evidence yet"}</summary>
      {quality.busy && <p role="status">Loading quality evidence…</p>}
      {quality.error && <p role="alert">Decision quality unavailable: {quality.error}</p>}
      {report && !quality.busy && <>
        <p>{report.headline}</p>
        <div className="core-quality-grid">
          <span><strong>{metrics.settled || 0}</strong><small>settled outcomes</small></span>
          <span><strong>{metrics.distinct_sessions || 0}</strong><small>market sessions</small></span>
          <span><strong>{percent(report.outcome_coverage)}</strong><small>due-window coverage</small></span>
          <span><strong>{percent(metrics.accuracy)}</strong><small>forecast accuracy</small></span>
          <span><strong>{metrics.brier_score == null ? "Unavailable" : Number(metrics.brier_score).toFixed(3)}</strong><small>Brier score · lower better</small></span>
        </div>
        <p className="core-muted">{report.records_considered} recorded decisions considered; {report.duplicates_or_overlaps_excluded} duplicate/overlapping windows excluded before outcomes. WAIT is abstention, not a neutral forecast.</p>
        {update.busy && <p role="status">{update.progress} <button type="button" className="core-text-button" onClick={update.cancel}>Cancel</button></p>}
        {(update.error || report.capture?.capacity_reached) && <p className="core-warning">{update.error || "Evidence storage is at capacity; no old observations are removed."}</p>}
        <button className="core-button secondary" type="button" disabled={update.busy} onClick={settle}>{update.busy ? "Updating…" : "Update outcomes"}</button>
        <details><summary>Quality limits and data coverage</summary>
          <p className="core-muted">{report.capture?.observations || 0} observations from {report.capture?.symbols || 0} symbols. Collection runs during explicit analysis and outcome checks, not continuously.</p>
          <ul>{(report.limitations || []).slice(0, 4).map((item, index) => <li key={index}>{item}</li>)}</ul>
        </details>
      </>}
    </details>
  </section>;
}
