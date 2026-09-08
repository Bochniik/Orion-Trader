import { describe, expect, it } from "vitest";
import { displayAxisTime, displayTime } from "./CandleChart";

describe("candlestick time display", () => {
  it("renders an intraday UTC candle in explicit market and local zones", () => {
    const timestamp = Date.parse("2026-07-17T13:30:00Z") / 1000;
    expect(displayTime(timestamp, "America/New_York")).toMatch(/09:30/);
    expect(displayTime(timestamp, "Europe/Bratislava")).toMatch(/15:30/);
  });

  it("keeps exchange-session dates as calendar dates", () => {
    expect(displayTime("2026-07-17", "America/New_York")).toMatch(/2026/);
  });

  it("formats the visible time axis in the selected timezone", () => {
    const timestamp = Date.parse("2026-07-17T13:30:00Z") / 1000;
    expect(displayAxisTime(timestamp, "America/New_York", 3)).toMatch(/09:30/);
    expect(displayAxisTime(timestamp, "Europe/Bratislava", 3)).toMatch(/15:30/);
  });
});
