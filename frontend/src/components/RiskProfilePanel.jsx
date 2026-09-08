import React, { useEffect, useState } from "react";
import { Flame, Scale, ShieldCheck } from "lucide-react";

const ICONS = {
  conservative: ShieldCheck,
  balanced: Scale,
  aggressive: Flame,
};

function percent(value) {
  return `${Number(value || 0).toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}%`;
}

export default function RiskProfilePanel({ data, saving, onSelect, onSavePlanning }) {
  const selected = data?.selected_mode || "balanced";
  const profiles = data?.available_profiles || [];
  const profile = data?.profile;
  const configuredAccount = data?.planning_account;
  const [planningEquity, setPlanningEquity] = useState("");
  const [planningCash, setPlanningCash] = useState("");

  useEffect(() => {
    setPlanningEquity(configuredAccount?.equity ?? "");
    setPlanningCash(configuredAccount?.cash ?? "");
  }, [configuredAccount?.equity, configuredAccount?.cash]);

  function savePlanning(event) {
    event.preventDefault();
    if (planningEquity === "" && planningCash === "") {
      onSavePlanning({ clear_planning_account: true });
      return;
    }
    onSavePlanning({
      planning_equity: Number(planningEquity),
      planning_cash: Number(planningCash),
    });
  }

  return <section className="card risk-profile-panel">
    <div className="risk-profile-heading">
      <div>
        <span className="assistant-only-badge">DETERMINISTIC RISK ENGINE</span>
        <h2>Choose how Orion treats risk</h2>
        <p>Orion assesses the setup. Code—not the language model—controls position size and exposure. Borrowed exposure stays disabled until replay and walk-forward validation pass.</p>
      </div>
      {saving && <span className="risk-profile-saving">Saving profile…</span>}
    </div>

    <div className="risk-mode-grid" role="radiogroup" aria-label="Recommendation risk mode">
      {profiles.map((item) => {
        const Icon = ICONS[item.mode] || Scale;
        const active = selected === item.mode;
        return <button
          type="button"
          role="radio"
          aria-checked={active}
          className={`risk-mode-card mode-${item.mode} ${active ? "active" : ""}`}
          key={item.mode}
          disabled={saving}
          onClick={() => onSelect(item.mode)}
        >
          <span className="risk-mode-icon"><Icon size={20} /></span>
          <span><strong>{item.label}</strong><small>{item.summary}</small></span>
          <i>{active ? "Selected" : "Choose"}</i>
        </button>;
      })}
    </div>

    {profile && <div className="risk-profile-limits">
      <span>Account risk <strong>{percent(profile.risk_percent)} / setup</strong></span>
      <span>Position exposure <strong>{percent(profile.max_position_percent)} max</strong></span>
      <span>Exposure ceiling <strong>{profile.max_instrument_leverage}x · unlevered</strong></span>
      <span>Daily stop <strong>{percent(profile.daily_loss_limit_percent)} manual limit</strong></span>
      <span>Minimum quality <strong>{profile.minimum_setup_quality}/100</strong></span>
      <span>Minimum R:R <strong>{profile.minimum_risk_reward}:1</strong></span>
    </div>}
    <form className="planning-account-form" onSubmit={savePlanning}>
      <div>
        <strong>External planning account</strong>
        <small>Optional. Enter the USD-equivalent capital you actually intend to manage outside OrionTrader. Otherwise new boards use the connected Alpaca Paper balance for simulation.</small>
      </div>
      <label>Planning equity (USD)
        <input type="number" min="1" step="0.01" value={planningEquity} onChange={(event) => setPlanningEquity(event.target.value)} placeholder="e.g. 10000" />
      </label>
      <label>Available cash (USD)
        <input type="number" min="0" step="0.01" value={planningCash} onChange={(event) => setPlanningCash(event.target.value)} placeholder="e.g. 5000" />
      </label>
      <button type="submit" className="ghost-btn" disabled={saving}>Save planning capital</button>
      {configuredAccount?.configured && <button type="button" className="clear-planning-btn" disabled={saving} onClick={() => { setPlanningEquity(""); setPlanningCash(""); onSavePlanning({ clear_planning_account: true }); }}>Use Paper balance</button>}
    </form>
    <p className="muted-text risk-profile-note">The profile is saved per user. Changing it affects new scans; saved historical boards retain the policy and evidence used when they were created.</p>
  </section>;
}
