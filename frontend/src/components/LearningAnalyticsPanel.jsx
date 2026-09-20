import { useCallback, useEffect, useMemo, useState } from "react";
import { BrainCircuit, Database, RefreshCw, ShieldCheck, HardDriveDownload } from "lucide-react";
import { createLearningBackup, getLearningAnalytics, getLearningStatus } from "./learningApi";
import DailyCloseReviewPanel from "./DailyCloseReviewPanel";
import "./LearningAnalyticsPanel.css";

const HORIZON_ORDER = ["30m", "1h", "3h", "5h"];
function formatNumber(value, digits = 1) { const number = Number(value); return Number.isFinite(number) ? number.toFixed(digits) : "—"; }
function Metric({ label, value, suffix = "" }) { return <div className="learning-metric"><span className="learning-metric-label">{label}</span><strong className="learning-metric-value">{value}{value !== "—" ? suffix : ""}</strong></div>; }
function HorizonCard({ group }) {
  const hasEvidence = Number(group?.outcome_count || 0) > 0;
  return <article className="learning-horizon-card"><div className="learning-horizon-head"><div><span className="learning-horizon-kicker">Horizon</span><h4>{group.horizon}</h4></div><span className={hasEvidence ? "learning-status-pill learning-status-pill--active" : "learning-status-pill"}>{hasEvidence ? `${group.outcome_count} resolved` : "Collecting data"}</span></div><div className="learning-metrics-grid"><Metric label="Directional accuracy" value={formatNumber(group.directional_accuracy_pct, 1)} suffix="%"/><Metric label="Brier score" value={formatNumber(group.brier_score, 4)}/><Metric label="ECE" value={formatNumber(group.expected_calibration_error_pct, 1)} suffix="%"/><Metric label="Average return" value={formatNumber(group.average_realized_return_pct, 2)} suffix="%"/></div><div className="learning-model-line"><span>Probability: {group.probability_engine_version || "—"}</span><span>Ranking: {group.ranking_version || "—"}</span></div></article>;
}

export default function LearningAnalyticsPanel({ pollIntervalMs = 30000 }) {
  const [status, setStatus] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [backupLoading, setBackupLoading] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async ({ quiet = false } = {}) => {
    try {
      if (quiet) setRefreshing(true); else setLoading(true);
      const [nextStatus, nextAnalytics] = await Promise.all([getLearningStatus(), getLearningAnalytics()]);
      setStatus(nextStatus); setAnalytics(nextAnalytics); setMessage("");
    } catch (error) { setMessage(error?.message || "Learning analytics unavailable."); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useEffect(() => {
    let mounted = true;
    if (mounted) load();
    const interval = window.setInterval(() => { if (mounted) load({ quiet: true }); }, pollIntervalMs);
    return () => { mounted = false; window.clearInterval(interval); };
  }, [load, pollIntervalMs]);
  const groups = useMemo(() => {
    const values = Array.isArray(analytics?.groups) ? analytics.groups : [];
    return [...values].sort((a, b) => { const ai = HORIZON_ORDER.indexOf(a.horizon); const bi = HORIZON_ORDER.indexOf(b.horizon); return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi); });
  }, [analytics]);
  async function backup() {
    try { setBackupLoading(true); const result = await createLearningBackup(); setMessage(result?.backup ? `Backup created: ${result.backup}` : "Backup created."); }
    catch (error) { setMessage(error?.message || "Backup failed."); }
    finally { setBackupLoading(false); }
  }
  const counts = status?.counts || analytics?.counts || {};
  const noRealData = Number(counts.predictions || 0) === 0 && Number(counts.forecasts || 0) === 0 && Number(counts.outcomes || 0) === 0;
  return <section className="learning-panel">
    <div className="learning-panel-header"><div className="learning-title-wrap"><div className="learning-icon"><BrainCircuit size={20}/></div><div><div className="learning-kicker">ORION EMPIRICAL MEMORY</div><h3>Learning Analytics</h3><p>Real outcomes from OrionTrader's own stored forecasts. This data measures the model; it does not silently retrain it.</p></div></div><div className="learning-actions"><button type="button" onClick={() => load({ quiet: true })} disabled={refreshing} className="learning-action-button"><RefreshCw size={16} className={refreshing ? "learning-spin" : ""}/>Refresh</button><button type="button" onClick={backup} disabled={backupLoading} className="learning-action-button"><HardDriveDownload size={16}/>Backup</button></div></div>
    <DailyCloseReviewPanel />
    {loading ? <div className="learning-empty">Loading Orion empirical memory…</div> : <><div className="learning-summary-grid"><div className="learning-summary-card"><Database size={18}/><div><span>Predictions</span><strong>{counts.predictions ?? 0}</strong></div></div><div className="learning-summary-card"><BrainCircuit size={18}/><div><span>Forecasts</span><strong>{counts.forecasts ?? 0}</strong></div></div><div className="learning-summary-card"><ShieldCheck size={18}/><div><span>Resolved outcomes</span><strong>{counts.outcomes ?? 0}</strong></div></div></div>{noRealData ? <div className="learning-empty"><strong>No live learning records yet.</strong><span>Orion is ready to start collecting predictions during the next regular US trading session.</span></div> : groups.length ? <div className="learning-horizon-grid">{groups.map((group) => <HorizonCard key={[group.probability_engine_version, group.ranking_version, group.horizon].join(":")} group={group}/>)}</div> : <div className="learning-empty">Predictions are stored, but no resolved probability outcomes are available yet.</div>}</>}
    {message ? <div className="learning-message">{message}</div> : null}
    <div className="learning-footer-note">Brier and ECE become meaningful only after enough resolved observations accumulate. A single correct prediction is not evidence that a model is calibrated.</div>
  </section>;
}
