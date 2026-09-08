import { useEffect, useState } from "react";
import { Bot, OctagonX, Play, Radar, ShieldCheck, Trash2 } from "lucide-react";
import { approveAutonomyProposal, clearAutonomyHistory, getAutonomyStatus, killAutonomy, runAutonomyNow, setAutonomyMode, updateAutonomySettings } from "../api/api";

const SETTING_LABELS = {
  scan_interval_minutes: "Scan interval (minutes)", candidate_count: "Screener + rotation budget", deep_analysis_count: "Deep AI analyses",
  minimum_confidence: "Minimum execution confidence %", max_position_percent: "Max position %", max_order_percent: "Max order %",
  max_daily_loss_percent: "Daily loss stop %", max_daily_trades: "Max daily trades", max_spread_percent: "Max spread %",
  minimum_price: "Minimum price", minimum_daily_volume: "Minimum daily volume",
};

const DISCOVERY_PRESETS = {
  focused: { candidate_count: 30, deep_analysis_count: 4 },
  balanced: { candidate_count: 60, deep_analysis_count: 6 },
  broad: { candidate_count: 100, deep_analysis_count: 8 },
};

const STATUS_LABELS = {
  observed_hold: "observed · no order", risk_rejected: "order blocked by risk", shadow: "shadow · eligible", pending_approval: "awaiting approval", submitted: "paper order submitted",
};

export default function AutonomyPanel({ brokerConnected, onPortfolioChanged, onStatusChanged }) {
  const [data, setData] = useState(null); const [settings, setSettings] = useState({});
  const [mode, setMode] = useState(null); const [activationPhrase, setActivationPhrase] = useState("");
  const [approvalPhrase, setApprovalPhrase] = useState(""); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const [proposalFilter, setProposalFilter] = useState("all");

  async function refresh() {
    try { const next = await getAutonomyStatus(); setData(next); setSettings(next.settings || {}); setMode((current) => current == null ? (next.mode || "off") : current); }
    catch (error) { setMessage(error.message); }
  }
  useEffect(() => { refresh(); const timer = window.setInterval(refresh, 10000); return () => window.clearInterval(timer); }, []);

  async function changeMode(event) {
    event.preventDefault(); try { setBusy(true); setMessage(""); await setAutonomyMode(mode, activationPhrase); setActivationPhrase(""); setMessage(`Orion paper agent mode: ${mode}`); await refresh(); await onStatusChanged?.(); }
    catch (error) { setMessage(error.message); } finally { setBusy(false); }
  }
  async function saveSettings(event) {
    event.preventDefault(); try { setBusy(true); const payload = Object.fromEntries(Object.keys(SETTING_LABELS).map((key) => [key, Number(settings[key])])); await updateAutonomySettings(payload); setMessage("Autonomous discovery and risk settings saved"); await refresh(); }
    catch (error) { setMessage(error.message); } finally { setBusy(false); }
  }
  async function applyDiscoveryPreset(name) {
    try { setBusy(true); const next = { ...settings, ...DISCOVERY_PRESETS[name] }; await updateAutonomySettings(Object.fromEntries(Object.keys(SETTING_LABELS).map((key) => [key, Number(next[key])]))); setSettings(next); setMessage(`${name[0].toUpperCase()}${name.slice(1)} discovery saved`); await refresh(); }
    catch (error) { setMessage(error.message); } finally { setBusy(false); }
  }
  async function runNow() { try { setBusy(true); await runAutonomyNow(); setMessage("Orion cycle scheduled now"); await onStatusChanged?.(); window.setTimeout(async () => { await refresh(); await onStatusChanged?.(); }, 1500); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function stopNow() { try { setBusy(true); const result = await killAutonomy(true); setMode("off"); setMessage(`Kill switch engaged · ${result.cancelled_order_ids?.length || 0} Orion open orders cancelled · positions were not liquidated`); await refresh(); await onStatusChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function approve(id) { try { setBusy(true); await approveAutonomyProposal(id, approvalPhrase); setApprovalPhrase(""); setMessage("Orion paper proposal approved and submitted"); await refresh(); await onPortfolioChanged?.(); await onStatusChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function clearHistory() {
    if (!window.confirm("Clear the visible Paper Lab history? Underlying safety audit records will be preserved.")) return;
    try {
      setBusy(true);
      const result = await clearAutonomyHistory();
      setMessage(`History view cleared · ${result.hidden_proposals} decisions and ${result.hidden_events} events hidden · safety audit preserved`);
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  const proposals = data?.proposals || []; const events = data?.events || []; const lastScan = data?.last_result?.scan;
  const actionableCount = proposals.filter((proposal) => proposal.action !== "HOLD").length;
  const holdCount = proposals.filter((proposal) => proposal.action === "HOLD").length;
  const filteredProposals = proposals.filter((proposal) => proposalFilter === "all" || (proposalFilter === "actionable" ? proposal.action !== "HOLD" : proposal.action === "HOLD"));

  return <section className="card autonomy-card">
    <div className="section-heading"><div className="card-title"><Bot size={20} /> Autonomous Orion · paper only</div><div className="autonomy-heading-actions"><button className="ghost-btn" type="button" onClick={clearHistory} disabled={busy || data?.mode !== "off" || data?.running} title="Stop the agent first. Audit records are retained."><Trash2 size={15} /> Clear visible history</button><button className="danger-btn kill-btn" type="button" onClick={stopNow} disabled={busy}><OctagonX size={16} /> Kill autonomous trading</button></div></div>
    <p className="broker-safety"><ShieldCheck size={17} /> AI proposes an action; deterministic limits alone own sizing and execution. Live trading, leverage, shorting and automatic liquidation are not supported.</p>
    {message && <p className={message.toLowerCase().includes("failed") || message.toLowerCase().includes("requires") || message.toLowerCase().includes("disabled") ? "error-text" : "success-text"}>{message}</p>}
    <div className="agent-status-grid"><div><span>Runtime mode</span><strong>{data?.mode || "off"}</strong></div><div><span>Scheduler</span><strong>{data?.running ? "Running cycle" : data?.next_run_at ? new Date(data.next_run_at).toLocaleString() : "Stopped"}</strong></div><div><span>Server execution gate</span><strong>{data?.server_autonomy_enabled ? "Enabled" : "Disabled"}</strong></div><div><span>Broker</span><strong>{brokerConnected ? "Alpaca Paper connected" : "Disconnected"}</strong></div></div>
    {!data?.server_autonomy_enabled && <p className="warning-text">Autonomous submission is server-disabled. Shadow and approval modes remain available. To permit autonomous paper orders, set ORION_AUTONOMY_ENABLED=true in backend/.env and restart.</p>}
    <form className="agent-mode-form" onSubmit={changeMode}><label>Operating mode<select value={mode || "off"} onChange={(event) => setMode(event.target.value)}><option value="off">Off</option><option value="shadow">Shadow — record only</option><option value="approval">Approval — ask before orders</option><option value="autonomous">Autonomous paper — bounded execution</option></select></label>{mode === "autonomous" && <label>Activation phrase<input value={activationPhrase} onChange={(event) => setActivationPhrase(event.target.value)} placeholder="ENABLE AUTONOMOUS PAPER" /></label>}<button className="primary-btn" type="submit" disabled={busy || (!brokerConnected && mode !== "off")}>Apply mode</button><button className="ghost-btn" type="button" onClick={runNow} disabled={busy || (data?.mode || "off") === "off"}><Play size={14} /> Run cycle now</button></form>

    {lastScan && <div className="scan-coverage"><div className="card-title"><Radar size={18} /> Last market discovery</div><div className="scan-coverage-grid"><div><span>Tradable universe</span><strong>{lastScan.universe_size?.toLocaleString()}</strong></div><div><span>Lifetime coverage</span><strong>{lastScan.lifetime_symbols_screened?.toLocaleString() ?? "—"}</strong></div><div><span>Live screener</span><strong>{lastScan.screener_symbols ?? "—"}</strong></div><div><span>Rotating discovery</span><strong>{lastScan.exploration_symbols ?? "—"}</strong></div><div><span>Snapshots checked</span><strong>{lastScan.screened_symbols}</strong></div><div><span>Passed filters</span><strong>{lastScan.qualified_count}</strong></div><div><span>Deep AI reviews</span><strong>{lastScan.ai_analysis_count ?? lastScan.candidates?.length ?? "—"}</strong></div></div><p>Every active tradable Alpaca equity is eligible, but Orion does not send all of them to AI in one cycle. It combines live activity/movers with a rotating universe slice, then applies price, volume and spread filters before the limited deep reviews. Lifetime coverage counts distinct symbols snapshot-screened for this user.</p>{lastScan.recent_deprioritized > 0 && <p className="muted-text">{lastScan.recent_deprioritized} recently reviewed symbols were deprioritized so new names can rotate in.</p>}{lastScan.partial_failure && <p className="warning-text">One market-discovery source partially failed; the cycle continued with available sources.</p>}</div>}

    <details><summary>Discovery and deterministic risk settings</summary><div className="discovery-presets"><span>Discovery preset</span>{Object.keys(DISCOVERY_PRESETS).map((name) => <button type="button" className="ghost-btn" key={name} disabled={busy} onClick={() => applyDiscoveryPreset(name)}>{name}</button>)}<small>Broader presets inspect and deeply evaluate more symbols, but use more market requests and AI tokens.</small></div><form className="risk-settings-grid" onSubmit={saveSettings}>{Object.entries(SETTING_LABELS).map(([key, label]) => <label key={key}>{label}<input type="number" min="0" step={key.includes("percent") || key === "minimum_price" ? "0.1" : "1"} value={settings[key] ?? ""} onChange={(event) => setSettings({ ...settings, [key]: event.target.value })} /></label>)}<button className="primary-btn" type="submit" disabled={busy}>Save settings</button></form></details>

    <div className="proposal-heading"><div><h3>Recent Orion decisions</h3><p>Confidence describes confidence in the displayed action. An 82% HOLD means Orion is strongly confident that waiting is preferable—not an 82% BUY signal.</p></div><div className="proposal-filters"><button type="button" className={proposalFilter === "all" ? "active" : ""} onClick={() => setProposalFilter("all")}>All {proposals.length}</button><button type="button" className={proposalFilter === "actionable" ? "active" : ""} onClick={() => setProposalFilter("actionable")}>BUY/SELL {actionableCount}</button><button type="button" className={proposalFilter === "holds" ? "active" : ""} onClick={() => setProposalFilter("holds")}>HOLD {holdCount}</button></div></div>
    {proposals.length === 0 ? <p>No autonomous decisions yet. Start Shadow mode and run a cycle to validate the pipeline without orders.</p> : filteredProposals.length === 0 ? <p>No decisions match this filter.</p> : <div className="proposal-list">{filteredProposals.slice(0, 15).map((proposal) => {
      const decision = proposal.decision || {}; const isHold = proposal.action === "HOLD";
      return <article key={proposal.id} className={`proposal ${isHold ? "proposal-hold" : ""}`}><div><strong>{proposal.action} {proposal.symbol}</strong><span>{proposal.confidence}% decision confidence · {isHold ? "observed · no order" : (STATUS_LABELS[proposal.status] || proposal.status)}</span></div>{decision.setup_type && decision.setup_type !== "none" && <p className="setup-type">Setup: {decision.setup_type.replace("_", " ")}{decision.candidate?.selection_reason ? ` · selected for ${decision.candidate.selection_reason}` : ""}</p>}<p>{proposal.thesis}</p>{decision.decision_factors?.length > 0 && <ul className="decision-factors">{decision.decision_factors.map((factor) => <li key={factor}>{factor}</li>)}</ul>}{isHold && decision.missing_confirmation && <p className="hold-note"><strong>What could change it:</strong> {decision.missing_confirmation}</p>} {!isHold && <p className="muted-text">{proposal.qty || 0} shares{proposal.limit_price ? ` · limit $${proposal.limit_price}` : ""}{proposal.invalidation_price ? ` · invalidation $${proposal.invalidation_price}` : ""}</p>}{proposal.risk?.reasons?.length > 0 && <p className={isHold ? "hold-note" : "warning-text"}>{isHold ? "No order: " : "Blocked: "}{proposal.risk.reasons.join("; ")}</p>}{proposal.status === "pending_approval" && <div className="proposal-approval"><input value={approvalPhrase} onChange={(event) => setApprovalPhrase(event.target.value)} placeholder="APPROVE ORION PAPER ORDER" /><button type="button" className="danger-btn" disabled={busy} onClick={() => approve(proposal.id)}>Approve paper order</button></div>}</article>;
    })}</div>}
    <details><summary>Audit trail</summary><div className="audit-list">{events.slice(0, 30).map((event) => <p key={event.id}><strong>{event.event_type}</strong> · {event.message}{event.details?.detail && <small>{event.details.detail}</small>} <span>{new Date(`${event.created_at}Z`).toLocaleString()}</span></p>)}</div></details>
  </section>;
}
