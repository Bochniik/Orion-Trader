import { useEffect, useRef } from "react";
import { createChart, LineSeries } from "lightweight-charts";

export default function BacktestChart({ data = [] }) {
  const container = useRef(null);
  useEffect(() => {
    if (!container.current) return undefined;
    const chart = createChart(container.current, { height: 260, layout: { background: { color: "#020617" }, textColor: "#cbd5e1" }, grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } }, rightPriceScale: { borderColor: "#334155" }, timeScale: { borderColor: "#334155" } });
    chart.addSeries(LineSeries, { color: "#a78bfa", lineWidth: 2, title: "Backtest equity" }).setData(data);
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: container.current?.clientWidth || 0 });
    resize(); window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.remove(); };
  }, [data]);
  return <div className="backtest-chart" ref={container} />;
}
