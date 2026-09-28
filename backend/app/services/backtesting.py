import math
from statistics import pstdev

import pandas as pd


class BacktestEngine:
    KINDS = {"sma_crossover", "rsi_reversion", "breakout"}

    @staticmethod
    def _rsi(close, period):
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
        rs = gain / loss.replace(0, float("nan"))
        return (100 - 100 / (1 + rs)).fillna(50)

    def run(self, ticker, history, kind, parameters=None, initial_cash=10_000, commission_bps=5, slippage_bps=5):
        if kind not in self.KINDS:
            raise ValueError("Unsupported strategy kind")
        parameters = parameters or {}
        if history is None or history.empty or not {"Open", "High", "Low", "Close"}.issubset(history.columns):
            raise ValueError("Backtests require non-empty OHLC history")
        frame = history.copy()
        if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
            raise ValueError(
                "Backtests require strictly increasing unique price-bar timestamps"
            )
        for column in ["Open", "High", "Low", "Close"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
        if len(frame) < 30:
            raise ValueError("Backtests require at least 30 price bars")

        entry, exit_signal = self._signals(frame, kind, parameters)
        allocation_value = float(parameters.get("allocation_percent", 100))
        stop_loss_value = float(parameters.get("stop_loss_percent", 0))
        take_profit_value = float(parameters.get("take_profit_percent", 0))
        if not 0 < allocation_value <= 100:
            raise ValueError("Allocation percent must be between 0 and 100")
        if not 0 <= stop_loss_value < 100 or take_profit_value < 0:
            raise ValueError("Stop loss and take profit parameters are invalid")
        if float(initial_cash) <= 0 or not 0 <= float(commission_bps) <= 1_000 or not 0 <= float(slippage_bps) <= 1_000:
            raise ValueError("Backtest cash and friction assumptions are invalid")
        allocation = allocation_value / 100
        stop_loss = stop_loss_value / 100
        take_profit = take_profit_value / 100
        friction = (float(commission_bps) + float(slippage_bps)) / 10_000
        cash = float(initial_cash)
        shares = 0
        entry_cost = None
        entry_date = None
        trades = []
        curve = []

        for index in range(1, len(frame)):
            row = frame.iloc[index]
            prior = index - 1
            execution_price = float(row["Open"])
            timestamp = frame.index[index]
            should_exit = bool(exit_signal.iloc[prior])
            reason = "signal"
            if shares and stop_loss and float(row["Low"]) <= entry_cost * (1 - stop_loss):
                execution_price = min(execution_price, entry_cost * (1 - stop_loss))
                should_exit, reason = True, "stop_loss"
            elif shares and take_profit and float(row["High"]) >= entry_cost * (1 + take_profit):
                execution_price = max(execution_price, entry_cost * (1 + take_profit))
                should_exit, reason = True, "take_profit"

            if shares and should_exit:
                proceeds = shares * execution_price * (1 - friction)
                pnl = proceeds - shares * entry_cost
                cash += proceeds
                trades.append({"entry_date": entry_date, "exit_date": str(timestamp.date()), "entry_price": round(entry_cost, 2), "exit_price": round(execution_price, 2), "shares": shares, "pnl": round(pnl, 2), "return_percent": round((execution_price / entry_cost - 1) * 100, 2), "exit_reason": reason})
                shares, entry_cost, entry_date = 0, None, None

            if not shares and bool(entry.iloc[prior]):
                buy_price = execution_price * (1 + friction)
                budget = cash * allocation
                quantity = math.floor(budget / buy_price)
                if quantity > 0:
                    cash -= quantity * buy_price
                    shares, entry_cost, entry_date = quantity, buy_price, str(timestamp.date())

            equity = cash + shares * float(row["Close"])
            curve.append({"time": str(timestamp.date()), "value": round(equity, 2)})

        final_close = float(frame["Close"].iloc[-1])
        final_equity = cash + shares * final_close
        metrics = self._metrics(curve, trades, initial_cash, final_equity)
        buy_hold = (final_close / float(frame["Close"].iloc[0]) - 1) * 100
        return {"ticker": str(ticker).upper(), "kind": kind, "parameters": parameters, "metrics": {**metrics, "buy_hold_return_percent": round(buy_hold, 2)}, "trades": trades, "equity_curve": curve, "open_position": shares > 0, "assumptions": {"signal_execution": "next bar open", "commission_bps": commission_bps, "slippage_bps": slippage_bps, "initial_cash": initial_cash}}

    def _signals(self, frame, kind, parameters):
        close = frame["Close"]
        if kind == "sma_crossover":
            fast = int(parameters.get("fast_period", 20)); slow = int(parameters.get("slow_period", 50))
            if fast < 2 or slow <= fast:
                raise ValueError("Slow SMA period must be greater than fast period")
            fast_sma, slow_sma = close.rolling(fast).mean(), close.rolling(slow).mean()
            return (fast_sma > slow_sma) & (fast_sma.shift(1) <= slow_sma.shift(1)), (fast_sma < slow_sma) & (fast_sma.shift(1) >= slow_sma.shift(1))
        if kind == "rsi_reversion":
            period = int(parameters.get("rsi_period", 14)); oversold = float(parameters.get("oversold", 30)); overbought = float(parameters.get("overbought", 70))
            if period < 2:
                raise ValueError("RSI period must be at least 2")
            if not 0 < oversold < overbought < 100:
                raise ValueError("RSI thresholds must satisfy 0 < oversold < overbought < 100")
            rsi = self._rsi(close, period)
            return rsi < oversold, rsi > overbought
        lookback = int(parameters.get("lookback", 20))
        if lookback < 2:
            raise ValueError("Breakout lookback must be at least 2")
        prior_high = frame["High"].rolling(lookback).max().shift(1)
        prior_low = frame["Low"].rolling(lookback).min().shift(1)
        return close > prior_high, close < prior_low

    @staticmethod
    def _metrics(curve, trades, initial_cash, final_equity):
        values = [point["value"] for point in curve]
        returns = [current / previous - 1 for previous, current in zip(values, values[1:]) if previous]
        peak, drawdown = None, 0
        for value in values:
            peak = value if peak is None else max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
        volatility = pstdev(returns) * math.sqrt(252) if len(returns) >= 2 else None
        annual_return = sum(returns) / len(returns) * 252 if returns else None
        wins = [trade for trade in trades if trade["pnl"] > 0]
        return {"final_equity": round(final_equity, 2), "total_return_percent": round((final_equity / initial_cash - 1) * 100, 2), "max_drawdown_percent": round(drawdown * 100, 2), "annualized_volatility_percent": round(volatility * 100, 2) if volatility is not None else None, "sharpe_ratio": round(annual_return / volatility, 2) if volatility else None, "completed_trades": len(trades), "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else None}
