import React from "react";
import { Calculator, CheckCircle2, CircleSlash2, ShieldAlert, Target } from "lucide-react";

function money(value, currency = "USD") {
  if (value == null) return "—";
  try {
    return Number(value).toLocaleString(undefined, {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: Number(value) < 10 ? 4 : 2,
    });
  } catch {
    return `${Number(value).toLocaleString()} ${currency || ""}`.trim();
  }
}

export default function TradeRecommendation({ plan }) {
  if (!plan) {
    return <div className="trade-plan trade-plan-empty"><CircleSlash2 size={17} /><span>No validated position plan was generated.</span></div>;
  }

  const qualified = plan.status === "qualified";
  const cfd = plan.instrument === "CFD_OPTIONAL";
  const failedGates = (plan.gates || []).filter((gate) => !gate.passed);
  const priceCurrency = plan.instrument_currency || "USD";
  const accountCurrency = plan.account_currency || priceCurrency;
  const hasLevels = plan.entry_price != null && plan.stop_loss != null && plan.take_profit != null;
  const statusCopy = {
    qualified: {
      title: "Validated setup — trigger confirmed",
      body: "The price/volume trigger and every sizing rule passed. Recheck the live quote before taking any external action.",
    },
    awaiting_trigger: {
      title: "Watch — waiting for breakout",
      body: plan.breakout_price != null
        ? `This is not a buy yet. Watch for a confirmed move through ${money(plan.breakout_price, priceCurrency)} with the required volume.`
        : "This is not a buy yet. Wait for the stated price-and-volume confirmation.",
    },
    extended: {
      title: "Watch — breakout is extended",
      body: "The planned breakout already moved beyond the permitted chase distance. Wait for a controlled retest instead of chasing.",
    },
    not_qualified: {
      title: "Not qualified at this risk standard",
      body: "Concrete watch levels are shown when available, but the evidence or expected reward did not clear the selected profile.",
    },
    sizing_unavailable: {
      title: "Levels ready — sizing unavailable",
      body: "The chart plan is concrete, but Orion could not safely convert the instrument into the account currency for position sizing.",
    },
    data_insufficient: {
      title: "Insufficient market structure",
      body: "Orion could not calculate reliable support, resistance and volatility from current OHLCV data. No price plan is inferred.",
    },
    blocked: {
      title: "Setup valid — account sizing blocked",
      body: "The setup passed, but the configured account cannot fund one unit within its risk and exposure ceilings.",
    },
    wait: {
      title: "Wait — no actionable setup",
      body: "The current evidence does not support an actionable entry.",
    },
  }[plan.status] || {
    title: "Research plan",
    body: "Review the deterministic checks before taking any external action.",
  };

  return <section className={`trade-plan ${qualified ? "qualified" : "waiting"} ${cfd ? "cfd-optional" : ""}`}>
    <div className="trade-plan-heading">
      <div>
        <span>{qualified ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}{statusCopy.title}</span>
        <h4>{plan.instrument_label}</h4>
      </div>
      <strong>{plan.setup_quality}/100 <small>setup quality</small></strong>
    </div>

    {hasLevels && <div className="trade-plan-levels">
      <span>Current<strong>{money(plan.current_price, priceCurrency)}</strong></span>
      <span>Planned entry<strong>{money(plan.entry_price, priceCurrency)}</strong></span>
      <span>Breakout trigger<strong>{money(plan.breakout_price, priceCurrency)}</strong></span>
      <span>Protective stop<strong>{money(plan.stop_loss, priceCurrency)}</strong></span>
      <span>Research target<strong>{money(plan.take_profit, priceCurrency)}</strong></span>
      <span>Expected R:R<strong>{plan.risk_reward == null ? "—" : `1:${plan.risk_reward}`}</strong></span>
    </div>}

    <p className="trade-plan-state"><Target size={15} />{plan.level_summary || statusCopy.body}</p>

    {qualified && <>
      <div className="trade-plan-sizing">
        <Calculator size={17} />
        <span>Risk ceiling<strong>{plan.quantity} units</strong></span>
        <span>Maximum planned loss<strong>{money(plan.estimated_max_loss, accountCurrency)} · {plan.risk_percent}%</strong></span>
        <span>Notional exposure<strong>{money(plan.notional_exposure, accountCurrency)} · {plan.exposure_percent}%</strong></span>
        <span>Estimated margin<strong>{money(plan.estimated_margin, accountCurrency)} at {plan.suggested_leverage}x</strong></span>
      </div>
    </>}

    <details className="trade-plan-audit">
      <summary>Decision audit: levels, trigger, instrument and size</summary>
      <div className="trade-gates">
        {(plan.gates || []).map((gate, index) => <div className={gate.passed ? "passed" : "failed"} key={`${gate.name}-${index}`}><strong>{gate.passed ? "Pass" : "Not met"} · {gate.name.replaceAll("_", " ")}</strong><span>{gate.detail}</span></div>)}
      </div>
      {(plan.warnings || []).map((warning) => <p className="trade-plan-warning" key={warning}>{warning}</p>)}
    </details>

    {!qualified && failedGates.length > 0 && <p className="trade-plan-blockers">Checks not met: {failedGates.map((gate) => gate.name.replaceAll("_", " ")).join(" · ")}</p>}
    <p className="trade-plan-boundary">External execution only · verify every value in your broker · setup quality is not a probability of profit</p>
  </section>;
}
