import React, { useState } from "react";
import { FlaskConical, Gauge, Radar } from "lucide-react";
import ExplosiveMovePanel from "./ExplosiveMovePanel";
import ExtremeMoveReplayPanel from "./ExtremeMoveReplayPanel";
import ExecutionSimulationPanel from "./ExecutionSimulationPanel";

export default function MoveLabWorkspace({ ticker, ...props }) {
  const [mode, setMode] = useState("scanner");
  const [executionSeed, setExecutionSeed] = useState(null);
  function stressReplayClose(seed) {
    setExecutionSeed({
      symbol: seed.symbol,
      reference_price: seed.reference_price,
      daily_volume: seed.daily_volume,
      order_type: "market",
      side: "buy",
      limit_price: "",
      protective_stop_price: "",
    });
    setMode("execution");
  }
  return <section className="move-lab-shell">
    <nav className="card move-lab-mode-tabs" aria-label="Move Lab mode">
      <button type="button" className={mode === "scanner" ? "active" : ""} onClick={() => setMode("scanner")}><Radar size={17} /><span>Live Scanner<small>Current preparation, ignition and danger</small></span></button>
      <button type="button" className={mode === "replay" ? "active" : ""} onClick={() => setMode("replay")}><FlaskConical size={17} /><span>Replay Lab<small>Historical 20%, 50% and 100% outcomes</small></span></button>
      <button type="button" className={mode === "execution" ? "active" : ""} onClick={() => setMode("execution")}><Gauge size={17} /><span>Execution Lab<small>Spread, gaps, fills, pauses and rejection</small></span></button>
    </nav>
    {mode === "scanner" && <ExplosiveMovePanel {...props} />}
    {mode === "replay" && <ExtremeMoveReplayPanel initialTicker={ticker} onOpenTicker={props.onOpenTicker} onStressExecution={stressReplayClose} />}
    {mode === "execution" && <ExecutionSimulationPanel initialTicker={ticker} initialPlan={executionSeed} />}
  </section>;
}
