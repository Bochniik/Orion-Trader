import { useEffect, useRef } from "react";
import { createChart, LineSeries } from "lightweight-charts";

export default function PerformanceChart({ comparison }) {
  const container = useRef(null);

  useEffect(() => {
    if (!container.current) return undefined;
    const chart = createChart(container.current, {
      height: 280,
      layout: { background: { color: "#020617" }, textColor: "#cbd5e1" },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155" },
    });
    const portfolioSeries = chart.addSeries(LineSeries, { color: "#22c55e", lineWidth: 2, title: "Portfolio" });
    const benchmarkSeries = chart.addSeries(LineSeries, { color: "#60a5fa", lineWidth: 2, title: comparison?.symbol || "Benchmark" });
    portfolioSeries.setData(comparison?.portfolio || []);
    benchmarkSeries.setData(comparison?.benchmark || []);
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: container.current?.clientWidth || 0 });
    resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.remove(); };
  }, [comparison]);

  return <div className="performance-chart" ref={container} />;
}
