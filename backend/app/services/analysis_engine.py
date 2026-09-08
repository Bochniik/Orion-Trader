import math

import pandas as pd


class AnalysisEngine:
    def calculate_sma(self, prices: pd.Series, period: int):
        return prices.rolling(window=period, min_periods=1).mean()

    def calculate_ema(self, prices: pd.Series, period: int):
        return prices.ewm(span=period, adjust=False, min_periods=1).mean()

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        numeric_prices = pd.to_numeric(prices, errors="coerce").dropna()
        if len(numeric_prices) < 2:
            return 50.0

        delta = numeric_prices.diff()
        gain = delta.clip(lower=0).rolling(window=period, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period, min_periods=1).mean()
        average_gain = float(gain.iloc[-1])
        average_loss = float(loss.iloc[-1])

        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        if average_gain == 0:
            return 0.0

        relative_strength = average_gain / average_loss
        return round(100 - (100 / (1 + relative_strength)), 2)

    def analyze(self, ticker: str, history):
        clean_ticker = str(ticker or "").strip().upper()
        if not clean_ticker:
            raise ValueError("Ticker is required")
        if history is None or getattr(history, "empty", True):
            raise ValueError(f"No price history found for {clean_ticker}")

        missing_columns = {"Close", "Volume"} - set(history.columns)
        if missing_columns:
            raise ValueError(
                "Price history is missing required columns: "
                + ", ".join(sorted(missing_columns))
            )

        close = pd.to_numeric(history["Close"], errors="coerce").dropna()
        volume = pd.to_numeric(history["Volume"], errors="coerce").reindex(close.index)
        if close.empty:
            raise ValueError(f"No valid closing prices found for {clean_ticker}")

        current_price = round(float(close.iloc[-1]), 2)
        rsi = self.calculate_rsi(close)
        sma_20 = round(float(self.calculate_sma(close, 20).iloc[-1]), 2)
        sma_50 = round(float(self.calculate_sma(close, 50).iloc[-1]), 2)
        ema_20 = round(float(self.calculate_ema(close, 20).iloc[-1]), 2)

        valid_volume = volume.dropna()
        if valid_volume.empty:
            latest_volume = 0.0
            average_volume = 0.0
        else:
            latest_volume = float(valid_volume.iloc[-1])
            average_volume = float(
                valid_volume.rolling(window=20, min_periods=1).mean().iloc[-1]
            )

        score = 50
        reasons = []

        if rsi < 30:
            score += 20
            reasons.append("RSI is below 30, so the stock may be oversold.")
        elif rsi > 70:
            score -= 20
            reasons.append("RSI is above 70, so the stock may be overbought.")
        else:
            reasons.append("RSI is neutral.")

        if current_price > sma_20:
            score += 10
            reasons.append("Price is above the 20-day moving average.")
        else:
            score -= 10
            reasons.append("Price is at or below the 20-day moving average.")

        if sma_20 > sma_50:
            score += 15
            reasons.append("The 20-day trend is above the 50-day trend.")
        else:
            score -= 15
            reasons.append("The 20-day trend is at or below the 50-day trend.")

        if current_price > ema_20:
            score += 10
            reasons.append("Price is above the 20-day EMA.")
        else:
            score -= 10
            reasons.append("Price is at or below the 20-day EMA.")

        if latest_volume > average_volume and average_volume > 0:
            score += 5
            reasons.append("Volume is above average.")
        else:
            reasons.append("Volume is not above average.")

        score = max(0, min(100, score))
        signal = "BUY" if score >= 70 else "SELL" if score <= 30 else "HOLD"

        indicators = {
            "rsi": rsi,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "ema_20": ema_20,
            "latest_volume": int(latest_volume) if math.isfinite(latest_volume) else 0,
            "average_volume_20": (
                int(average_volume) if math.isfinite(average_volume) else 0
            ),
        }

        return {
            "ticker": clean_ticker,
            "price": current_price,
            "signal": signal,
            "confidence_score": score,
            "indicators": indicators,
            "reasons": reasons,
            "data_points": len(close),
        }
