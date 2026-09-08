export function chartTimeKey(time) {
  if (typeof time === "object" && time) return `${time.year}-${time.month}-${time.day}`;
  return String(time);
}

export function movingAverage(candles, window) {
  let total = 0;
  return candles.flatMap((candle, index) => {
    total += candle.close;
    if (index >= window) total -= candles[index - window].close;
    return index >= window - 1 ? [{ time: candle.time, value: total / window }] : [];
  });
}

export function exponentialAverage(candles, window) {
  if (!candles.length) return [];
  const multiplier = 2 / (window + 1);
  let value = candles[0].close;
  return candles.map((candle, index) => {
    value = index === 0 ? candle.close : candle.close * multiplier + value * (1 - multiplier);
    return { time: candle.time, value };
  });
}

export function buildCandleDetails(candles) {
  return new Map(candles.map((candle, index) => {
    const previousClose = index > 0 ? candles[index - 1].close : candle.open;
    const change = candle.close - previousClose;
    return [chartTimeKey(candle.time), { ...candle, change, changePercent: previousClose ? change / previousClose * 100 : 0 }];
  }));
}
