import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, createChart, HistogramSeries, LineSeries } from "lightweight-charts";
import { getCandles, getQuote } from "../api/api";
import { buildCandleDetails, chartTimeKey, exponentialAverage, movingAverage } from "../chartMath";

const CHART_RANGES = [
  { label: "1D", period: "1d", interval: "1m", live: true },
  { label: "5D", period: "5d", interval: "5m", live: true },
  { label: "1M", period: "1mo", interval: "30m", live: true },
  { label: "3M", period: "3mo", interval: "1d" },
  { label: "6M", period: "6mo", interval: "1d" },
  { label: "YTD", period: "ytd", interval: "1d" },
  { label: "1Y", period: "1y", interval: "1d" },
  { label: "5Y", period: "5y", interval: "1wk" },
];

const OVERLAYS = [
  { id: "sma20", label: "SMA 20", color: "#f59e0b" },
  { id: "ema20", label: "EMA 20", color: "#a78bfa" },
  { id: "sma50", label: "SMA 50", color: "#38bdf8" },
  { id: "volume", label: "Volume", color: "#64748b" },
];

export function displayTime(time, timeZone = "America/New_York") {
  if (typeof time === "string") {
    return new Date(`${time}T00:00:00`).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
  }
  if (typeof time === "object" && time) {
    return new Date(time.year, time.month - 1, time.day).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
  }
  return new Date(Number(time) * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone });
}

export function displayAxisTime(time, timeZone = "America/New_York", tickMarkType = 3) {
  if (typeof time === "string" || (typeof time === "object" && time)) {
    const value = typeof time === "string" ? new Date(`${time}T00:00:00`) : new Date(time.year, time.month - 1, time.day);
    if (tickMarkType === 0) return value.toLocaleDateString([], { year: "numeric" });
    if (tickMarkType === 1) return value.toLocaleDateString([], { month: "short" });
    return value.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  const value = new Date(Number(time) * 1000);
  if (tickMarkType === 0) return value.toLocaleDateString([], { year: "numeric", timeZone });
  if (tickMarkType === 1) return value.toLocaleDateString([], { month: "short", timeZone });
  if (tickMarkType === 2) return value.toLocaleDateString([], { month: "short", day: "numeric", timeZone });
  return value.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false, timeZone });
}

function money(value) {
  if (!Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  return number.toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: number < 10 ? 3 : 2, maximumFractionDigits: number < 10 ? 3 : 2 });
}

function compact(value) {
  return Number(value || 0).toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 2 });
}

function intervalSeconds(interval) {
  return { "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600 }[interval] || 60;
}

function currentCandleTime(interval) {
  const seconds = intervalSeconds(interval);
  return Math.floor(Date.now() / 1000 / seconds) * seconds;
}

export default function CandleChart({ ticker, refreshKey }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef({});
  const latestCandleRef = useRef(null);
  const detailsRef = useRef(new Map());
  const [chartMessage, setChartMessage] = useState("Loading chart...");
  const [liveMessage, setLiveMessage] = useState("");
  const [selectedRange, setSelectedRange] = useState(CHART_RANGES.find((range) => range.label === "6M"));
  const [visible, setVisible] = useState({ sma20: true, ema20: false, sma50: true, volume: true });
  const [inspector, setInspector] = useState(null);
  const [summary, setSummary] = useState(null);
  const [timeMode, setTimeMode] = useState("market");
  const selectedTimeZone = timeMode === "market" ? "America/New_York" : Intl.DateTimeFormat().resolvedOptions().timeZone;

  useEffect(() => {
    if (!chartContainerRef.current) return undefined;
    const chart = createChart(chartContainerRef.current, {
      height: 500,
      layout: { background: { type: ColorType.Solid, color: "#020617" }, textColor: "#cbd5e1", fontFamily: "Arial, Helvetica, sans-serif" },
      grid: { vertLines: { color: "#111c31" }, horzLines: { color: "#111c31" } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#64748b", labelBackgroundColor: "#334155" }, horzLine: { color: "#64748b", labelBackgroundColor: "#334155" } },
      rightPriceScale: { borderColor: "#334155", scaleMargins: { top: 0.08, bottom: 0.27 } },
      timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false, rightOffset: 4, barSpacing: 7, minBarSpacing: 1, tickMarkFormatter: (time, tickMarkType) => displayAxisTime(time, "America/New_York", tickMarkType) },
      localization: { timeFormatter: (time) => displayTime(time, "America/New_York") },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444", priceLineVisible: true, lastValueVisible: true });
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    const sma20 = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const ema20 = chart.addSeries(LineSeries, { color: "#a78bfa", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, visible: false });
    const sma50 = chart.addSeries(LineSeries, { color: "#38bdf8", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    chartRef.current = chart;
    seriesRef.current = { candles, volume, sma20, ema20, sma50 };

    chart.subscribeCrosshairMove((parameter) => {
      if (!parameter.time || !parameter.point || parameter.point.x < 0 || parameter.point.y < 0) return;
      const detail = detailsRef.current.get(chartTimeKey(parameter.time));
      if (detail) setInspector(detail);
    });
    const resize = () => chart.applyOptions({ width: chartContainerRef.current?.clientWidth || 0 });
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(chartContainerRef.current);
    return () => { observer.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = {}; };
  }, []);

  useEffect(() => {
    chartRef.current?.applyOptions({ localization: { timeFormatter: (time) => displayTime(time, selectedTimeZone) } });
    chartRef.current?.timeScale().applyOptions({ tickMarkFormatter: (time, tickMarkType) => displayAxisTime(time, selectedTimeZone, tickMarkType) });
  }, [selectedTimeZone]);

  useEffect(() => {
    Object.entries(visible).forEach(([id, isVisible]) => seriesRef.current[id]?.applyOptions({ visible: isVisible }));
  }, [visible]);

  useEffect(() => {
    let cancelled = false;
    async function loadCandles() {
      try {
        setChartMessage(`Loading ${selectedRange.label} chart...`);
        setLiveMessage("");
        const data = await getCandles(ticker, selectedRange.period, selectedRange.interval);
        if (cancelled) return;
        const candles = (data.candles || []).map((candle) => ({ ...candle, open: Number(candle.open), high: Number(candle.high), low: Number(candle.low), close: Number(candle.close), volume: Number(candle.volume || 0) }));
        if (!candles.length) throw new Error("No candle data is available for this range");
        detailsRef.current = buildCandleDetails(candles);
        latestCandleRef.current = candles.at(-1);
        seriesRef.current.candles.setData(candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
        seriesRef.current.volume.setData(candles.map((candle) => ({ time: candle.time, value: candle.volume, color: candle.close >= candle.open ? "rgba(34,197,94,.38)" : "rgba(239,68,68,.38)" })));
        seriesRef.current.sma20.setData(movingAverage(candles, 20));
        seriesRef.current.ema20.setData(exponentialAverage(candles, 20));
        seriesRef.current.sma50.setData(movingAverage(candles, 50));
        const first = candles[0]; const last = candles.at(-1); const periodChange = last.close - first.open;
        setSummary({ change: periodChange, changePercent: first.open ? periodChange / first.open * 100 : 0, high: Math.max(...candles.map((item) => item.high)), low: Math.min(...candles.map((item) => item.low)), averageVolume: candles.reduce((sum, item) => sum + item.volume, 0) / candles.length, bars: candles.length });
        setInspector(detailsRef.current.get(chartTimeKey(last.time)));
        chartRef.current.timeScale().fitContent();
        setChartMessage("");
      } catch (error) { if (!cancelled) setChartMessage(error.message); }
    }
    if (seriesRef.current.candles) loadCandles();
    return () => { cancelled = true; };
  }, [ticker, refreshKey, selectedRange]);

  useEffect(() => {
    if (!selectedRange.live || !ticker || !seriesRef.current.candles) { setLiveMessage(""); return undefined; }
    let cancelled = false;
    async function updateLiveCandle() {
      try {
        const quote = await getQuote(ticker); const price = Number(quote.price); const current = latestCandleRef.current;
        if (!price || !current || cancelled || typeof current.time === "string") return;
        const time = currentCandleTime(selectedRange.interval);
        const maximumLiveGap = intervalSeconds(selectedRange.interval) * 2;
        if (Math.abs(time - Number(current.time)) > maximumLiveGap) {
          setLiveMessage(`Latest quote · ${money(price)} · chart history is outside the current market interval`);
          return;
        }
        const updated = time > current.time ? { time, open: price, high: price, low: price, close: price, volume: 0 } : { ...current, close: price, high: Math.max(current.high, price), low: Math.min(current.low, price) };
        latestCandleRef.current = updated;
        seriesRef.current.candles.update(updated);
        const priorDetail = detailsRef.current.get(chartTimeKey(current.time));
        const previousClose = time > current.time ? current.close : current.close - Number(priorDetail?.change || 0);
        const change = price - previousClose;
        const detail = { ...updated, change, changePercent: previousClose ? change / previousClose * 100 : 0 };
        detailsRef.current.set(chartTimeKey(updated.time), detail); setInspector(detail);
        setLiveMessage(`Live quote refresh · ${money(price)} · every 5 seconds`);
      } catch { if (!cancelled) setLiveMessage("Live quote refresh paused"); }
    }
    updateLiveCandle(); const timer = window.setInterval(updateLiveCandle, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [ticker, selectedRange]);

  const positive = Number(inspector?.change || 0) >= 0;
  const chartState = chartMessage ? (chartMessage.startsWith("Loading ") ? "loading" : "error") : "ready";
  const liveState = liveMessage === "Live quote refresh paused" ? "paused" : liveMessage.includes("outside the current market interval") ? "stale" : "live";
  const liveLabel = liveState === "paused" ? "Live refresh paused" : liveState === "stale" ? "Latest quote available" : "Live market feed";

  return <div className="advanced-chart">
    <div className="chart-toolbar"><div className="range-buttons" aria-label="Chart range selector">{CHART_RANGES.map((range) => <button type="button" key={range.label} className={range.label === selectedRange.label ? "range-btn active" : "range-btn"} onClick={() => setSelectedRange(range)}>{range.label}</button>)}</div><div className="chart-time-controls"><button type="button" className={timeMode === "market" ? "active" : ""} onClick={() => setTimeMode("market")}>New York market time</button><button type="button" className={timeMode === "local" ? "active" : ""} onClick={() => setTimeMode("local")}>My local time</button><span className="chart-interval-note">{selectedRange.interval} candles{selectedRange.live ? " · live quote" : ""}</span></div></div>
    <div className="indicator-toolbar" aria-label="Chart overlays">{OVERLAYS.map((overlay) => <button type="button" key={overlay.id} className={visible[overlay.id] ? "indicator-toggle active" : "indicator-toggle"} style={{ "--indicator-color": overlay.color }} onClick={() => setVisible((current) => ({ ...current, [overlay.id]: !current[overlay.id] }))}><i />{overlay.label}</button>)}</div>
    {inspector && <div className="chart-inspector"><div><span>{timeMode === "market" ? "New York time" : "Local time"}</span><strong>{displayTime(inspector.time, selectedTimeZone)}</strong></div><div><span>Open</span><strong>{money(inspector.open)}</strong></div><div><span>High</span><strong>{money(inspector.high)}</strong></div><div><span>Low</span><strong>{money(inspector.low)}</strong></div><div><span>Close</span><strong>{money(inspector.close)}</strong></div><div><span>Change</span><strong className={positive ? "green" : "red"}>{positive ? "+" : ""}{money(inspector.change)} ({positive ? "+" : ""}{Number(inspector.changePercent).toFixed(2)}%)</strong></div><div><span>Range</span><strong>{money(inspector.high - inspector.low)}</strong></div><div><span>Volume</span><strong>{compact(inspector.volume)}</strong></div></div>}
    {summary && <div className="chart-period-summary" aria-label={`${ticker} chart market context`}><span><strong>{ticker}</strong> · {selectedRange.label} / {selectedRange.interval}</span><span>{selectedRange.label} change <strong className={summary.change >= 0 ? "green" : "red"}>{summary.change >= 0 ? "+" : ""}{summary.changePercent.toFixed(2)}%</strong></span><span>High <strong>{money(summary.high)}</strong></span><span>Low <strong>{money(summary.low)}</strong></span><span>Avg volume <strong>{compact(summary.averageVolume)}</strong></span><span>Latest bar <strong>{inspector ? displayTime(inspector.time, selectedTimeZone) : "—"}</strong></span><span>{summary.bars} bars</span></div>}
    {chartMessage && <div className={`chart-status chart-status-${chartState}`} role={chartState === "error" ? "alert" : "status"} aria-live="polite"><span className="chart-status-indicator" aria-hidden="true" /><div><strong>{chartState === "loading" ? "Loading market history" : "Chart data unavailable"}</strong><span>{chartMessage}</span></div></div>}
    {!chartMessage && liveMessage && <div className={`chart-live-message chart-live-${liveState}`} role="status" aria-live="polite"><span className="chart-live-indicator" aria-hidden="true" /><div><strong>{liveLabel}</strong><span>{liveMessage}</span></div></div>}
    <div ref={chartContainerRef} className="chart-box" aria-label={`${ticker} interactive candlestick chart`} />
    <p className="chart-help">Drag to pan · scroll or pinch to zoom · move the crosshair for exact OHLC, change and volume.</p>
  </div>;
}
