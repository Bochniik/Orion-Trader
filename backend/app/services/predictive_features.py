"""Leakage-aware historical and rolling real-time feature construction.

Feature calculations are deterministic.  The module deliberately retains null
values when the source resolution cannot support a feature; one-minute bars are
never presented as five-, fifteen-, or thirty-second observations.
"""

import math
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


NEW_YORK = ZoneInfo("America/New_York")
HORIZON_SECONDS = {
    "30s": 30,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "1h": 3_600,
}

def label_direction(actual_return, *, spread_bps=0.0, realized_volatility=0.0, steps=1):
    """Canonical target label used by both training and settlement."""
    noise = max(0.0003, (float(spread_bps) / 10000) * 1.5,
                float(realized_volatility) * math.sqrt(max(1, int(steps))) * 0.35)
    value = float(actual_return)
    return "UP" if value > noise else "DOWN" if value < -noise else "NEUTRAL"

FEATURE_SCHEMA = (
    "return_5s", "return_15s", "return_30s", "return_1m", "return_3m",
    "return_5m", "price_momentum", "momentum_acceleration", "ema_9",
    "ema_20", "ema_9_slope", "ema_20_slope", "sma_9_slope",
    "sma_20_slope", "vwap", "distance_from_vwap", "vwap_reclaim_rejection",
    "rsi_14", "atr_14", "realized_volatility", "volatility_ratio",
    "current_volume_rate", "relative_volume", "volume_acceleration",
    "bid", "ask", "spread_percent", "bid_size", "ask_size",
    "quote_imbalance", "trade_frequency", "opening_range_position",
    "distance_from_intraday_high", "distance_from_intraday_low",
    "distance_from_previous_day_high", "distance_from_previous_day_low",
    "sector_momentum", "index_momentum", "relative_strength_market",
    "relative_strength_sector",
)

MODEL_FEATURES = tuple(
    feature for feature in FEATURE_SCHEMA
    if feature not in {"ema_9", "ema_20", "vwap", "bid", "ask"}
)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(value):
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(timezone.utc)
    return parsed.tz_convert(timezone.utc).isoformat()


def _normalize_ohlcv(history):
    if not isinstance(history, pd.DataFrame) or history.empty:
        raise ValueError("Intraday OHLCV history is required")
    frame = history.copy()
    columns = {str(column).lower(): column for column in frame.columns}
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(columns):
        raise ValueError("Intraday history requires Open, High, Low, Close and Volume")
    frame = frame.rename(columns={columns[name]: name.title() for name in required})
    optional = {}
    for name in ("trade count", "trade_count", "vwap"):
        if name in columns:
            optional[columns[name]] = "TradeCount" if "trade" in name else "ProviderVwap"
    frame = frame.rename(columns=optional)
    keep = ["Open", "High", "Low", "Close", "Volume"]
    keep.extend(column for column in ("TradeCount", "ProviderVwap") if column in frame)
    frame = frame[keep]
    frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame = frame[~frame.index.isna()].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    for column in keep:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["Open", "High", "Low", "Close", "Volume"]
    )
    frame = frame[
        (frame["Open"] > 0) & (frame["High"] > 0)
        & (frame["Low"] > 0) & (frame["Close"] > 0)
        & (frame["Volume"] >= 0)
    ]
    if frame.empty:
        raise ValueError("No valid intraday OHLCV rows remain")
    return frame


def _rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    ratio = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + ratio)
    return result.where(loss != 0, 100).where(gain != 0, 0).where(
        ~((gain == 0) & (loss == 0)), 50
    )


def _opening_range(frame):
    output = pd.Series(np.nan, index=frame.index, dtype=float)
    local_dates = frame.index.tz_convert(NEW_YORK).date
    for _, positions in pd.Series(range(len(frame)), index=frame.index).groupby(local_dates):
        indexes = positions.index
        group = frame.loc[indexes]
        first = group.iloc[:5]
        running_high = first["High"].cummax()
        running_low = first["Low"].cummin()
        high = pd.Series(running_high.iloc[-1], index=group.index)
        low = pd.Series(running_low.iloc[-1], index=group.index)
        high.iloc[:len(first)] = running_high.values
        low.iloc[:len(first)] = running_low.values
        width = (high - low).replace(0, np.nan)
        output.loc[group.index] = ((group["Close"] - low) / width).values
    return output


def _previous_day_levels(frame):
    dates = pd.Series(frame.index.tz_convert(NEW_YORK).date, index=frame.index)
    daily = frame.groupby(dates).agg({"High": "max", "Low": "min"})
    prior_high = daily["High"].shift(1).to_dict()
    prior_low = daily["Low"].shift(1).to_dict()
    return (
        dates.map(prior_high).astype(float),
        dates.map(prior_low).astype(float),
    )


def _aligned_momentum(reference, index, periods=5):
    if not isinstance(reference, pd.DataFrame) or reference.empty:
        return pd.Series(np.nan, index=index, dtype=float)
    try:
        normalized = _normalize_ohlcv(reference)
    except ValueError:
        return pd.Series(np.nan, index=index, dtype=float)
    momentum = normalized["Close"].pct_change(periods, fill_method=None)
    return momentum.reindex(index, method="ffill", tolerance=pd.Timedelta(seconds=60))


def build_intraday_feature_frame(history, *, market_history=None, sector_history=None):
    """Build one-minute-close features with no future rows in any feature."""
    frame = _normalize_ohlcv(history)
    close, high, low, volume = (
        frame["Close"], frame["High"], frame["Low"], frame["Volume"]
    )
    features = pd.DataFrame(index=frame.index)
    # Unsupported at one-minute resolution.  They become available only from
    # genuine timestamped stream observations.
    features[["return_5s", "return_15s", "return_30s"]] = np.nan
    for minutes in (1, 3, 5):
        features[f"return_{minutes}m"] = close.pct_change(minutes, fill_method=None)
    features["price_momentum"] = features["return_5m"]
    features["momentum_acceleration"] = (
        features["return_1m"] - features["return_1m"].shift(1)
    )
    ema9 = close.ewm(span=9, adjust=False, min_periods=9).mean()
    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    sma9 = close.rolling(9, min_periods=9).mean()
    sma20 = close.rolling(20, min_periods=20).mean()
    features["ema_9"], features["ema_20"] = ema9, ema20
    features["ema_9_slope"] = ema9.pct_change(3, fill_method=None)
    features["ema_20_slope"] = ema20.pct_change(3, fill_method=None)
    features["sma_9_slope"] = sma9.pct_change(3, fill_method=None)
    features["sma_20_slope"] = sma20.pct_change(3, fill_method=None)

    typical = (high + low + close) / 3
    dates = pd.Series(frame.index.tz_convert(NEW_YORK).date, index=frame.index)
    cumulative_value = (typical * volume).groupby(dates).cumsum()
    cumulative_volume = volume.groupby(dates).cumsum().replace(0, np.nan)
    vwap = cumulative_value / cumulative_volume
    features["vwap"] = vwap
    features["distance_from_vwap"] = close / vwap - 1
    prior_distance = features["distance_from_vwap"].shift(1)
    features["vwap_reclaim_rejection"] = np.select(
        [(prior_distance <= 0) & (features["distance_from_vwap"] > 0),
         (prior_distance >= 0) & (features["distance_from_vwap"] < 0)],
        [1.0, -1.0], default=0.0,
    )
    features["rsi_14"] = _rsi(close)
    previous_close = close.shift(1)
    true_range = pd.concat([
        high - low, (high - previous_close).abs(), (low - previous_close).abs()
    ], axis=1).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean()
    features["atr_14"] = atr
    returns = close.pct_change(fill_method=None)
    realized = returns.rolling(20, min_periods=20).std(ddof=1)
    features["realized_volatility"] = realized
    features["volatility_ratio"] = (
        true_range / true_range.rolling(20, min_periods=20).mean().shift(1)
    )
    current_rate = volume / 60
    average_rate = volume.rolling(20, min_periods=10).mean().shift(1) / 60
    features["current_volume_rate"] = current_rate
    features["relative_volume"] = current_rate / average_rate.replace(0, np.nan)
    features["volume_acceleration"] = (
        current_rate / current_rate.rolling(5, min_periods=3).mean().shift(1).replace(0, np.nan) - 1
    )
    for column in ("bid", "ask", "spread_percent", "bid_size", "ask_size", "quote_imbalance"):
        features[column] = np.nan
    features["trade_frequency"] = (
        frame["TradeCount"] / 60 if "TradeCount" in frame else np.nan
    )
    features["opening_range_position"] = _opening_range(frame)
    intraday_high = high.groupby(dates).cummax()
    intraday_low = low.groupby(dates).cummin()
    features["distance_from_intraday_high"] = close / intraday_high - 1
    features["distance_from_intraday_low"] = close / intraday_low - 1
    previous_high, previous_low = _previous_day_levels(frame)
    features["distance_from_previous_day_high"] = close / previous_high.values - 1
    features["distance_from_previous_day_low"] = close / previous_low.values - 1
    index_momentum = _aligned_momentum(market_history, frame.index)
    sector_momentum = _aligned_momentum(sector_history, frame.index)
    features["sector_momentum"] = sector_momentum
    features["index_momentum"] = index_momentum
    features["relative_strength_market"] = features["return_5m"] - index_momentum
    features["relative_strength_sector"] = features["return_5m"] - sector_momentum
    features["price"] = close
    features["source_resolution_seconds"] = 60
    return features.replace([np.inf, -np.inf], np.nan)


def latest_historical_snapshot(feature_frame):
    if not isinstance(feature_frame, pd.DataFrame) or feature_frame.empty:
        raise ValueError("A non-empty feature frame is required")
    row = feature_frame.iloc[-1]
    features = {name: _finite(row.get(name)) for name in FEATURE_SCHEMA}
    available = sum(value is not None for value in features.values())
    return {
        "timestamp": _iso(feature_frame.index[-1]),
        "price": _finite(row.get("price")),
        "features": features,
        "feature_coverage_percent": round(available / len(FEATURE_SCHEMA) * 100, 2),
        "source_resolution_seconds": int(row.get("source_resolution_seconds") or 60),
        "unavailable_subminute_features": ["return_5s", "return_15s", "return_30s"],
    }


def build_training_samples(symbol, feature_frame, *, spread_bps=5.0):
    """Create multi-horizon targets strictly after each feature timestamp."""
    if not isinstance(feature_frame, pd.DataFrame) or feature_frame.empty:
        return []
    resolution = int(feature_frame["source_resolution_seconds"].iloc[-1])
    samples = []
    price = feature_frame["price"]
    for horizon, seconds in HORIZON_SECONDS.items():
        if seconds < resolution or seconds % resolution:
            continue
        steps = seconds // resolution
        future = price.shift(-steps)
        future_return = future / price - 1
        volatility = feature_frame["realized_volatility"].fillna(
            price.pct_change(fill_method=None).expanding().std(ddof=1)
        )
        threshold = pd.concat([
            pd.Series(max(0.0003, float(spread_bps) / 10_000 * 1.5), index=price.index),
            volatility * math.sqrt(max(1, steps)) * 0.35,
        ], axis=1).max(axis=1)
        for position in range(len(feature_frame) - steps):
            # Row counts must not turn overnight gaps or missing minutes into
            # a nominal short-horizon target.
            if (feature_frame.index[position + steps] - feature_frame.index[position]).total_seconds() != seconds:
                continue
            actual = _finite(future_return.iloc[position])
            current_price = _finite(price.iloc[position])
            future_price = _finite(future.iloc[position])
            noise = _finite(threshold.iloc[position])
            if actual is None or current_price is None or future_price is None or noise is None:
                continue
            snapshot = {
                name: _finite(feature_frame.iloc[position].get(name))
                for name in FEATURE_SCHEMA
            }
            available = sum(snapshot[name] is not None for name in MODEL_FEATURES)
            if available < max(8, int(len(MODEL_FEATURES) * 0.35)):
                continue
            direction = "UP" if actual > noise else "DOWN" if actual < -noise else "NEUTRAL"
            samples.append({
                "symbol": str(symbol).upper(),
                "timestamp": _iso(feature_frame.index[position]),
                "feature_cutoff": _iso(feature_frame.index[position]),
                "outcome_timestamp": _iso(feature_frame.index[position + steps]),
                "horizon": horizon,
                "price": current_price,
                "future_price": future_price,
                "actual_return": actual,
                "actual_direction": direction,
                "neutral_threshold": noise,
                "features": snapshot,
                "source_resolution_seconds": resolution,
            })
    return samples


class RealTimeFeatureEngine:
    """Per-user rolling public-market buffers; credentials are never accepted."""

    def __init__(self, max_records=5_000):
        self.max_records = max(500, min(int(max_records), 20_000))
        self._records = defaultdict(lambda: deque(maxlen=self.max_records))
        self._seen_sequences = defaultdict(lambda: deque(maxlen=self.max_records * 2))
        self._seen_sets = defaultdict(set)
        self._lock = threading.RLock()

    def ingest(self, user_id, events):
        added = 0
        for event in events or []:
            event_type = str(event.get("type") or "").lower()
            if event_type not in {"quote", "trade", "bar"}:
                continue
            symbol = str(event.get("symbol") or "").upper()
            data = event.get("data") or {}
            if not symbol or not isinstance(data, dict):
                continue
            key = (str(user_id), symbol)
            sequence = event.get("sequence")
            identity = sequence if sequence is not None else (
                event_type, data.get("timestamp"), data.get("price"), data.get("close")
            )
            with self._lock:
                if identity in self._seen_sets[key]:
                    continue
                seen = self._seen_sequences[key]
                if len(seen) == seen.maxlen:
                    self._seen_sets[key].discard(seen.popleft())
                seen.append(identity)
                self._seen_sets[key].add(identity)
                record = self._event_record(event_type, data)
                if record:
                    self._records[key].append(record)
                    added += 1
        return added

    def _event_record(self, event_type, data):
        try:
            timestamp = pd.Timestamp(data.get("timestamp"))
            if pd.isna(timestamp) or timestamp.tzinfo is None:
                return None
        except (TypeError, ValueError):
            return None
        timestamp = timestamp.tz_convert(timezone.utc)
        bid, ask = _finite(data.get("bid")), _finite(data.get("ask"))
        price = _finite(data.get("price"))
        if price is None:
            price = _finite(data.get("close"))
        if price is None and bid is not None and ask is not None and bid + ask > 0:
            price = (bid + ask) / 2
        if price is None:
            return None
        return {
            "timestamp": timestamp,
            "event_type": event_type,
            "price": price,
            "high": _finite(data.get("high")),
            "low": _finite(data.get("low")),
            "volume": _finite(data.get("volume") or data.get("size")) or 0.0,
            "trade_count": _finite(data.get("trade_count")) or (1.0 if event_type == "trade" else 0.0),
            "vwap": _finite(data.get("vwap")),
            "bid": bid,
            "ask": ask,
            "bid_size": _finite(data.get("bid_size")),
            "ask_size": _finite(data.get("ask_size")),
            "spread_percent": _finite(data.get("spread_percent")),
        }

    def snapshot(self, user_id, symbol, *, liquidity=None, market_momentum=None,
                 sector_momentum=None, previous_day_high=None,
                 previous_day_low=None):
        key = (str(user_id), str(symbol).upper())
        with self._lock:
            records = [dict(record) for record in self._records.get(key, [])]
        if len(records) < 2:
            raise ValueError("The real-time feature buffer needs at least two market observations")
        records.sort(key=lambda item: item["timestamp"])
        now = records[-1]["timestamp"]
        prices = np.asarray([item["price"] for item in records], dtype=float)
        timestamps = [item["timestamp"] for item in records]

        def timed_return(seconds):
            cutoff = now - timedelta(seconds=seconds)
            indexes = [index for index, value in enumerate(timestamps) if value <= cutoff]
            if not indexes:
                return None
            prior = prices[indexes[-1]]
            return prices[-1] / prior - 1 if prior > 0 else None

        def ema(values, span):
            if len(values) < span:
                return None
            return _finite(pd.Series(values).ewm(span=span, adjust=False).mean().iloc[-1])

        returns = {seconds: timed_return(seconds) for seconds in (5, 15, 30, 60, 180, 300)}
        ema9, ema20 = ema(prices, 9), ema(prices, 20)
        ema9_previous = ema(prices[:-3], 9) if len(prices) > 11 else None
        ema20_previous = ema(prices[:-3], 20) if len(prices) > 22 else None
        bars = [item for item in records if item["event_type"] == "bar"]
        recent = [item for item in records if item["timestamp"] >= now - timedelta(seconds=60)]
        prior = [item for item in records if now - timedelta(seconds=120) <= item["timestamp"] < now - timedelta(seconds=60)]
        volume_type = "trade" if any(item["event_type"] == "trade" for item in records) else "bar"
        current_volume = sum(item["volume"] for item in recent if item["event_type"] == volume_type)
        prior_volume = sum(item["volume"] for item in prior if item["event_type"] == volume_type)
        weighted = [(item["price"], item["volume"]) for item in records if item["volume"] > 0]
        vwap = (
            sum(price * weight for price, weight in weighted) / sum(weight for _, weight in weighted)
            if weighted and sum(weight for _, weight in weighted) > 0 else None
        )
        price_series = pd.Series(prices)
        rsi = _finite(_rsi(price_series).iloc[-1]) if len(prices) >= 15 else None
        atr = None
        if len(bars) >= 14:
            bar_frame = pd.DataFrame(bars[-30:])
            previous = bar_frame["price"].shift(1)
            tr = pd.concat([
                (bar_frame["high"] - bar_frame["low"]).abs(),
                (bar_frame["high"] - previous).abs(),
                (bar_frame["low"] - previous).abs(),
            ], axis=1).max(axis=1)
            atr = _finite(tr.tail(14).mean())
        tick_returns = price_series.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()
        realized = _finite(tick_returns.tail(50).std(ddof=1)) if len(tick_returns) >= 10 else None
        current_range = (
            max(item["price"] for item in recent) - min(item["price"] for item in recent)
            if len(recent) >= 2 else None
        )
        prior_range = (
            max(item["price"] for item in prior) - min(item["price"] for item in prior)
            if len(prior) >= 2 else None
        )
        volatility_ratio = current_range / prior_range if prior_range not in (None, 0) else None
        latest_quote = next((item for item in reversed(records) if item["bid"] is not None and item["ask"] is not None), {})
        bid_size, ask_size = latest_quote.get("bid_size"), latest_quote.get("ask_size")
        quote_imbalance = (
            (bid_size - ask_size) / (bid_size + ask_size)
            if bid_size is not None and ask_size is not None and bid_size + ask_size > 0 else None
        )
        local_date = now.tz_convert(NEW_YORK).date()
        today = [item for item in records if item["timestamp"].tz_convert(NEW_YORK).date() == local_date]
        intraday_high = max(item["high"] or item["price"] for item in today)
        intraday_low = min(item["low"] or item["price"] for item in today)
        opening = [
            item for item in today
            if item["timestamp"].tz_convert(NEW_YORK).time() <= datetime.strptime("09:35", "%H:%M").time()
        ]
        opening_high = max((item["high"] or item["price"] for item in opening), default=None)
        opening_low = min((item["low"] or item["price"] for item in opening), default=None)
        opening_position = (
            (prices[-1] - opening_low) / (opening_high - opening_low)
            if opening_high is not None and opening_low is not None and opening_high > opening_low else None
        )
        average_rate = _finite((liquidity or {}).get("average_volume_rate_per_second"))
        current_rate = current_volume / 60
        relative_volume = current_rate / average_rate if average_rate not in (None, 0) else None
        sector_value, market_value = _finite(sector_momentum), _finite(market_momentum)
        features = {
            "return_5s": returns[5], "return_15s": returns[15],
            "return_30s": returns[30], "return_1m": returns[60],
            "return_3m": returns[180], "return_5m": returns[300],
            "price_momentum": returns[300],
            "momentum_acceleration": (
                returns[60] - timed_return(120) if returns[60] is not None and timed_return(120) is not None else None
            ),
            "ema_9": ema9, "ema_20": ema20,
            "ema_9_slope": ema9 / ema9_previous - 1 if ema9 and ema9_previous else None,
            "ema_20_slope": ema20 / ema20_previous - 1 if ema20 and ema20_previous else None,
            "sma_9_slope": _slope(prices, 9), "sma_20_slope": _slope(prices, 20),
            "vwap": vwap,
            "distance_from_vwap": prices[-1] / vwap - 1 if vwap else None,
            "vwap_reclaim_rejection": _vwap_state(prices, vwap),
            "rsi_14": rsi, "atr_14": atr,
            "realized_volatility": realized, "volatility_ratio": volatility_ratio,
            "current_volume_rate": current_rate, "relative_volume": relative_volume,
            "volume_acceleration": current_volume / prior_volume - 1 if prior_volume > 0 else None,
            "bid": latest_quote.get("bid"), "ask": latest_quote.get("ask"),
            "spread_percent": latest_quote.get("spread_percent"),
            "bid_size": bid_size, "ask_size": ask_size,
            "quote_imbalance": quote_imbalance,
            "trade_frequency": sum(item["trade_count"] for item in recent if item["event_type"] == volume_type) / 60,
            "opening_range_position": opening_position,
            "distance_from_intraday_high": prices[-1] / intraday_high - 1 if intraday_high else None,
            "distance_from_intraday_low": prices[-1] / intraday_low - 1 if intraday_low else None,
            "distance_from_previous_day_high": prices[-1] / previous_day_high - 1 if previous_day_high else None,
            "distance_from_previous_day_low": prices[-1] / previous_day_low - 1 if previous_day_low else None,
            "sector_momentum": sector_value, "index_momentum": market_value,
            "relative_strength_market": returns[300] - market_value if returns[300] is not None and market_value is not None else None,
            "relative_strength_sector": returns[300] - sector_value if returns[300] is not None and sector_value is not None else None,
        }
        clean = {name: _finite(features.get(name)) for name in FEATURE_SCHEMA}
        available = sum(value is not None for value in clean.values())
        return {
            "timestamp": now.isoformat(), "price": _finite(prices[-1]),
            "features": clean,
            "feature_coverage_percent": round(available / len(FEATURE_SCHEMA) * 100, 2),
            "source_resolution_seconds": _observed_resolution(timestamps),
            "buffer_records": len(records),
            "buffer_started_at": timestamps[0].isoformat(),
            "buffer_ended_at": timestamps[-1].isoformat(),
            "quote_as_of": _iso(latest_quote.get("timestamp")),
            "volume_as_of": _iso(next((item["timestamp"] for item in reversed(records) if item["event_type"] == volume_type), None)),
        }

    def clear_user(self, user_id):
        user = str(user_id)
        with self._lock:
            keys = [key for key in self._records if key[0] == user]
            for key in keys:
                self._records.pop(key, None)
                self._seen_sequences.pop(key, None)
                self._seen_sets.pop(key, None)
        return len(keys)


def _slope(values, period):
    if len(values) < period + 3:
        return None
    current = float(np.mean(values[-period:]))
    previous = float(np.mean(values[-period - 3:-3]))
    return current / previous - 1 if previous else None


def _vwap_state(prices, vwap):
    if vwap is None or len(prices) < 2:
        return None
    previous, current = prices[-2] - vwap, prices[-1] - vwap
    return 1.0 if previous <= 0 < current else -1.0 if previous >= 0 > current else 0.0


def _observed_resolution(timestamps):
    if len(timestamps) < 2:
        return None
    differences = [
        max(0.001, (current - prior).total_seconds())
        for prior, current in zip(timestamps[:-1], timestamps[1:])
        if current > prior
    ]
    return round(float(np.median(differences)), 3) if differences else None


def feature_schema_contract():
    return {
        "version": "orion-features-v1",
        "features": list(FEATURE_SCHEMA),
        "model_features": list(MODEL_FEATURES),
        "horizons": HORIZON_SECONDS,
        "extension_contract": "Add a named deterministic calculator and provenance entry without changing existing feature meanings.",
        "leakage_contract": "Every feature uses evidence at or before its timestamp; targets live only in later outcome rows.",
        "resolution_contract": "Unsupported sub-minute fields remain null; one-minute bars are never upsampled into sub-minute evidence.",
    }
