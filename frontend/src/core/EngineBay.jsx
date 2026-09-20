import { useEffect, useState } from "react";
import { Activity, ChevronRight, Gauge, Settings2, X } from "lucide-react";
import { getEngineBay, getTickerDecisionPipeline } from "../api/api";
import "./engineBay.css";

function statusClass(status) {
  return String(status || "unavailable").toLowerCase();
}


function PerformancePanel({ performance }) {
  if (!performance || performance.status !== "available") {
    return <div className="engine-insufficient">
      {performance?.label || "Insufficient evidence"}
      {performance?.minimum_sample ? <small>Minimum sample per horizon: {performance.minimum_sample}</small> : null}
    </div>;
  }
  const rows = performance.performance_by_horizon || [];
  return <div className="engine-performance">
    <div className="engine-performance-summary">
      <span><small>Settled predictions</small><strong>{performance.settled_predictions ?? 0}</strong></span>
      <span><small>Log loss</small><strong>{performance.log_loss ?? "Unavailable"}</strong></span>
      <span><small>Last evaluation</small><strong>{performance.last_evaluation ?? "Unavailable"}</strong></span>
    </div>
    <div className="engine-performance-table">
      {rows.map((row) => <div className={"engine-performance-row " + row.status} key={row.horizon || row.model_version}>
        <span><b>{row.horizon || "Unknown"}</b><small>n={row.sample_size}</small></span>
        {row.status === "available" ? <>
          <span><small>Accuracy</small><strong>{row.accuracy_percent ?? "—"}%</strong></span>
          <span><small>Brier</small><strong>{row.brier_score ?? "—"}</strong></span>
          <span><small>Calibration error</small><strong>{row.calibration_error_percent ?? "—"}%</strong></span>
        </> : <span className="engine-performance-insufficient">Insufficient evidence</span>}
      </div>)}
    </div>
  </div>;
}

export default function EngineBay({ open, onClose, selectedTicker }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [pipeline, setPipeline] = useState(null);

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    setError("");
    getEngineBay()
      .then((result) => { if (active) setData(result); })
      .catch((err) => { if (active) setError(err?.message || "Engine Bay unavailable."); });
    return () => { active = false; };
  }, [open]);

  useEffect(() => {
    if (!open || !selectedTicker) { setPipeline(null); return undefined; }
    let active = true;
    getTickerDecisionPipeline(selectedTicker).then((value) => { if (active) setPipeline(value); }).catch(() => { if (active) setPipeline(null); });
    return () => { active = false; };
  }, [open, selectedTicker]);

  if (!open) return null;
  const engines = data?.engines || [];
  const detail = selected || null;

  return (
    <div className="engine-bay-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <aside className="engine-bay" aria-label="Engine Bay">
        <header className="engine-bay-header">
          <div><p className="core-eyebrow">UNDER THE HOOD</p><h2>Engine Bay</h2><span>Runtime truth, model state and evaluation provenance.</span></div>
          <button type="button" aria-label="Close Engine Bay" onClick={onClose}><X size={18} /></button>
        </header>

        {data?.telemetry && <div className="engine-telemetry">
          <div><Gauge size={14}/><span>Online</span><strong>{data.telemetry.engines_online ?? "—"}</strong></div>
          <div><Activity size={14}/><span>Pipeline</span><strong>{data.telemetry.data_pipeline_health || "unavailable"}</strong></div>
          <div><Settings2 size={14}/><span>Cycle</span><strong>{data.telemetry.cycle_running ? "RUNNING" : "IDLE"}</strong></div>
        </div>}

        {error && <div className="core-error" role="alert">{error}</div>}

        {pipeline && <section className="engine-pipeline">
          <div className="engine-pipeline-heading"><span>Current decision pipeline</span><strong>{pipeline.ticker}</strong></div>
          {pipeline.layers.map((layer) => <div className="engine-pipeline-row" key={layer.id}><span>{layer.name}</span><strong className={statusClass(layer.status)}>{layer.status}</strong></div>)}
          <small>{pipeline.semantics}</small>
        </section>}

        <div className="engine-list">
          {engines.map((engine) => (
            <button type="button" className="engine-row" key={engine.id} onClick={() => setSelected(engine)}>
              <span className={`engine-status-dot ${statusClass(engine.status)}`} />
              <span className="engine-row-copy"><strong>{engine.name}</strong><small>{engine.purpose}</small></span>
              <span className={`engine-status ${statusClass(engine.status)}`}>{engine.status}</span>
              <ChevronRight size={14}/>
            </button>
          ))}
        </div>

        {detail && <section className="engine-detail">
          <button type="button" className="engine-detail-close" onClick={() => setSelected(null)}>Back to engines</button>
          <p className="core-eyebrow">{detail.module}</p>
          <h3>{detail.name}</h3>
          <p>{detail.purpose}</p>
          <dl>
            <div><dt>Status</dt><dd>{detail.status}</dd></div>
            <div><dt>Validation</dt><dd>{detail.performance_state || "unavailable"}</dd></div>
            <div><dt>Model version</dt><dd>{detail.model_version || "Unavailable"}</dd></div>
            <div><dt>Horizons</dt><dd>{Array.isArray(detail.supported_horizons) && detail.supported_horizons.length ? detail.supported_horizons.join(", ") : "Unavailable"}</dd></div>
          </dl>
          {detail.performance ? <PerformancePanel performance={detail.performance} /> : <div className="engine-insufficient">Insufficient evidence / not independently scored.</div>}
        </section>}

        <footer>{data?.semantics || "Missing metrics are shown as unavailable."}</footer>
      </aside>
    </div>
  );
}
