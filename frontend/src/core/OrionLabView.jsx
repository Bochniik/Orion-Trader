import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Beaker,
  CheckCircle2,
  CircleDot,
  FlaskConical,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  getResearchExperiments,
  getResearchRegistry,
  getResearchProspectiveStatus,
} from "../api/api";

function pct(value, digits = 2) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : "—";
}
function num(value, digits = 4) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}
function statusTone(value = "") {
  const s = String(value).toUpperCase();
  if (s.includes("REPLICATED") || s.includes("READY") || s.includes("APPROVED")) return "good";
  if (s.includes("REJECTED") || s.includes("FAILED") || s.includes("DISABLED") || s.includes("NOT_APPROVED")) return "bad";
  return "neutral";
}
function StatusPill({ children }) {
  return <span className={`orion-lab-status ${statusTone(children)}`}>{children}</span>;
}
function Metric({ label, value, hint }) {
  return (
    <div className="orion-lab-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}

export default function OrionLabView() {
  const [registry, setRegistry] = useState(null);
  const [prospective, setProspective] = useState(null);
  const [experiments, setExperiments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  async function load({ silent = false } = {}) {
    silent ? setRefreshing(true) : setLoading(true);
    try {
      const [registryData, prospectiveData, experimentData] = await Promise.all([
        getResearchRegistry(),
        getResearchProspectiveStatus(),
        getResearchExperiments(30),
      ]);
      setRegistry(registryData || null);
      setProspective(prospectiveData || null);
      setExperiments(experimentData?.experiments || []);
      setError("");
    } catch (err) {
      setError(err?.message || "Could not load Orion research registry.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load({ silent: true }), 60000);
    return () => window.clearInterval(timer);
  }, []);

  const models = registry?.models || [];
  const prospectiveRows = prospective?.horizons || registry?.prospective || [];
  const v3 = useMemo(
    () => models.find((model) => model.model_id === "logistic_v3_conservative"),
    [models]
  );
  const settled = prospectiveRows.reduce((sum, row) => sum + Number(row.settled_count ?? row.settled ?? 0), 0);
  const pending = prospectiveRows.reduce((sum, row) => sum + Number(row.pending_count ?? row.pending ?? 0), 0);
  const total = prospectiveRows.reduce((sum, row) => sum + Number(row.prediction_count ?? row.predictions ?? 0), 0);

  return (
    <section className="orion-lab-view">
      <header className="orion-lab-hero">
        <div>
          <div className="orion-lab-eyebrow"><FlaskConical size={14} /> ORION RESEARCH LAB</div>
          <h1>Model validation,<br />without guesswork.</h1>
          <p>Research results, model governance and prospective validation in one place. Production deployment stays separated from experimentation.</p>
        </div>
        <div className="orion-lab-hero-actions">
          <button type="button" className="orion-lab-refresh" onClick={() => load({ silent: true })} disabled={refreshing}>
            <RefreshCw size={15} className={refreshing ? "orion-lab-spin" : ""} />
            {refreshing ? "Refreshing" : "Refresh"}
          </button>
          <div className="orion-lab-governance">
            <ShieldCheck size={16} />
            <span><strong>Manual approval required</strong><small>Automatic deployment disabled</small></span>
          </div>
        </div>
      </header>

      {error ? <div className="orion-lab-error" role="alert">{error}</div> : null}

      {loading ? (
        <div className="orion-lab-loading"><Activity size={18} /> Loading research registry…</div>
      ) : (
        <>
          <div className="orion-lab-summary-grid">
            <Metric label="Registered models" value={models.length} hint="Research governance" />
            <Metric label="Experiments indexed" value={registry?.experiment_count ?? 0} hint="Stored validation runs" />
            <Metric label="Prospective predictions" value={total} hint={`${settled} settled · ${pending} pending`} />
            <Metric label="Production auto-deploy" value="OFF" hint="Manual gate enforced" />
          </div>

          <div className="orion-lab-grid">
            <article className="orion-lab-panel orion-lab-v3">
              <div className="orion-lab-panel-head">
                <div><span className="orion-lab-kicker">CURRENT CANDIDATE</span><h2>Logistic v3 Conservative</h2></div>
                <StatusPill>{v3?.research_status || "FROZEN_PROSPECTIVE_CANDIDATE"}</StatusPill>
              </div>
              <p className="orion-lab-copy">Frozen research model. Prospective observations must not be used to tune this version.</p>
              <div className="orion-lab-horizons">
                {(v3?.horizons || []).map((row) => (
                  <div className="orion-lab-horizon" key={row.horizon}>
                    <div><strong>{row.horizon}</strong><StatusPill>{row.validation_status}</StatusPill></div>
                    <small>{row.notes}</small>
                  </div>
                ))}
              </div>
            </article>

            <article className="orion-lab-panel">
              <div className="orion-lab-panel-head">
                <div><span className="orion-lab-kicker">FORWARD VALIDATION</span><h2>Prospective v3</h2></div>
                <span className="orion-lab-live"><CircleDot size={13} /> COLLECTING</span>
              </div>
              <div className="orion-lab-prospective">
                {prospectiveRows.length ? prospectiveRows.map((row) => (
                  <div className="orion-lab-prospective-row" key={row.horizon}>
                    <div className="orion-lab-prospective-title">
                      <strong>{row.horizon}</strong>
                      <span>{Number(row.settled_count ?? row.settled ?? 0)} settled / {Number(row.prediction_count ?? 0)} total</span>
                    </div>
                    <div className="orion-lab-prospective-metrics">
                      <span>Accuracy<strong>{pct(row.accuracy_pct)}</strong></span>
                      <span>Brier<strong>{num(row.brier)}</strong></span>
                      <span>Log loss<strong>{num(row.log_loss)}</strong></span>
                    </div>
                  </div>
                )) : <p className="orion-lab-muted">No prospective observations have been registered yet.</p>}
              </div>
            </article>
          </div>

          <article className="orion-lab-panel">
            <div className="orion-lab-panel-head"><div><span className="orion-lab-kicker">MODEL REGISTRY</span><h2>Research governance</h2></div></div>
            <div className="orion-lab-model-table">
              <div className="orion-lab-model-header"><span>Model</span><span>Research status</span><span>Production</span></div>
              {models.map((model) => (
                <div className="orion-lab-model-row" key={model.model_id}>
                  <span><strong>{model.display_name}</strong><small>{model.model_id}</small></span>
                  <span><StatusPill>{model.research_status}</StatusPill></span>
                  <span><StatusPill>{model.production_status}</StatusPill></span>
                </div>
              ))}
            </div>
          </article>

          <article className="orion-lab-panel">
            <div className="orion-lab-panel-head">
              <div><span className="orion-lab-kicker">EXPERIMENT HISTORY</span><h2>Indexed validation runs</h2></div>
              <span className="orion-lab-count">{experiments.length} shown</span>
            </div>
            <div className="orion-lab-experiments">
              {experiments.length ? experiments.map((experiment) => (
                <div className="orion-lab-experiment" key={experiment.experiment_id}>
                  <span className="orion-lab-experiment-icon">
                    {String(experiment.experiment_type).includes("holdout") ? <CheckCircle2 size={15} /> :
                     String(experiment.experiment_type).includes("challenger") ? <Beaker size={15} /> :
                     <CircleDot size={15} />}
                  </span>
                  <span><strong>{experiment.experiment_type}</strong><small>{experiment.generated_at || experiment.imported_at || "Stored experiment"}</small></span>
                  <code>{experiment.source_path}</code>
                </div>
              )) : <p className="orion-lab-muted">No indexed experiments.</p>}
            </div>
          </article>

          <div className="orion-lab-footer-note"><XCircle size={15} /> Research results never promote a model to production automatically.</div>
        </>
      )}
    </section>
  );
}
