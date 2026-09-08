import { describe, expect, it } from "vitest";
import { buildCandleDetails, chartTimeKey, exponentialAverage, movingAverage } from "./chartMath";

const candles = [
  { time: "2026-01-01", open: 9, high: 11, low: 8, close: 10, volume: 100 },
  { time: "2026-01-02", open: 10, high: 13, low: 9, close: 12, volume: 200 },
  { time: "2026-01-03", open: 12, high: 15, low: 11, close: 14, volume: 300 },
];

describe("candlestick calculations", () => {
  it("calculates rolling averages without look-ahead values", () => {
    expect(movingAverage(candles, 2)).toEqual([
      { time: "2026-01-02", value: 11 },
      { time: "2026-01-03", value: 13 },
    ]);
  });

  it("calculates deterministic exponential averages", () => {
    const values = exponentialAverage(candles, 2).map((point) => point.value);
    expect(values[0]).toBe(10);
    expect(values[1]).toBeCloseTo(11.333333, 6);
    expect(values[2]).toBeCloseTo(13.111111, 6);
  });

  it("measures each bar from the previous close", () => {
    const details = buildCandleDetails(candles);
    expect(details.get("2026-01-02")).toMatchObject({ change: 2, changePercent: 20 });
  });

  it("normalizes business-day chart keys", () => {
    expect(chartTimeKey({ year: 2026, month: 7, day: 17 })).toBe("2026-7-17");
  });
});
