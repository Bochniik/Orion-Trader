import { ArrowRight, ShieldCheck, Sparkles } from "lucide-react";
import OrionMark from "./OrionMark";
import { ASSISTANT_PILLARS } from "../uiPresentation";

export default function AssistantHero({
  ticker,
  brokerConnected = false,
  agentMode = "off",
  onOpenResearch,
  onAskOrion,
}) {
  return <section className="assistant-hero">
    <div className="hero-glow hero-glow-one" aria-hidden="true" />
    <div className="hero-glow hero-glow-two" aria-hidden="true" />
    <div className="hero-orbit-wrap"><OrionMark size={112} className="hero-orion-mark" /></div>

    <div className="hero-copy">
      <div className="hero-kicker"><Sparkles size={15} /> AI research cockpit</div>
      <h2>See the market clearly.<br /><span>Keep the decision yours.</span></h2>
      <p>Orion combines market evidence, portfolio context and disciplined risk tools into one calm workspace—while every real-money decision stays in your hands.</p>
      <div className="hero-actions">
        <button type="button" className="hero-primary-btn" onClick={onOpenResearch}>Research {ticker}<ArrowRight size={16} /></button>
        <button type="button" className="hero-secondary-btn" onClick={onAskOrion}><Sparkles size={16} /> Ask Orion</button>
      </div>
      <div className="hero-pillars">{ASSISTANT_PILLARS.map((pillar) => <span key={pillar}><ShieldCheck size={13} />{pillar}</span>)}</div>
    </div>

    <div className="hero-signal-deck" aria-label="Current workspace summary">
      <div className="signal-deck-head"><span>Orion focus</span><strong>{ticker}</strong></div>
      <div className="signal-trace" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /></div>
      <div className="signal-layer"><span>Market evidence</span><b>Scanning</b></div>
      <div className="signal-layer"><span>Paper broker</span><b className={brokerConnected ? "online" : ""}>{brokerConnected ? "Connected" : "Optional"}</b></div>
      <div className="signal-layer"><span>Paper agent</span><b className={agentMode !== "off" ? "watching" : ""}>{agentMode === "off" ? "Off" : agentMode}</b></div>
      <div className="signal-deck-foot"><span className="pulse-dot" /> Real execution remains external</div>
    </div>
  </section>;
}
