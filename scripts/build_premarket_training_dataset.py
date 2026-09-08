from __future__ import annotations

import argparse
from datetime import time
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.premarket_predictive_engine import FEATURE_NAMES, extract_predictive_features


PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
SNAPSHOT_TIMES = (time(8, 30), time(9, 0), time(9, 15), time(9, 25))
PREMARKET_HORIZONS = (5, 15, 30)
OPEN_HORIZONS = (5, 15, 30, 60)


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "symbol": "ticker",
        "t": "timestamp",
        "o": "Open",
        "h": "High",
        "l": "Low",
        "c": "Close",
        "v": "Volume",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    renamed = {column: aliases.get(column.lower(), column) for column in frame.columns}
    frame = frame.rename(columns=renamed)
    required = ["ticker", "timestamp", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing raw minute columns: {', '.join(missing)}")
    frame = frame[required].copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna().sort_values(["ticker", "timestamp"])
    return frame


def edge_threshold_pct(features) -> float:
    rv = features.get("realized_volatility_30m")
    if rv is None or not np.isfinite(float(rv)):
        return 0.20
    return float(np.clip(float(rv) * 1.25, 0.12, 0.80))


def label_return(return_pct, threshold):
    if return_pct is None or not np.isfinite(return_pct):
        return None
    if return_pct > threshold:
        return "UP"
    if return_pct < -threshold:
        return "DOWN"
    return "NO_EDGE"


def close_at_or_after(
    frame: pd.DataFrame,
    target: pd.Timestamp,
    *,
    max_delay_minutes: int = 5,
):
    """Return the first observed close at/after target within a small tolerance.

    Using the last bar *before* a future horizon silently creates zero/shortened
    returns on sparse premarket feeds. Labels must be based on an observation
    that occurs after the forecast horizon has actually elapsed.
    """
    eligible = frame.loc[
        (frame.index >= target)
        & (frame.index <= target + pd.Timedelta(minutes=max_delay_minutes))
    ]
    if eligible.empty:
        return None
    return float(eligible["Close"].iloc[0])


def previous_regular_close(local: pd.DataFrame, day) -> float | None:
    earlier = local.loc[local.index.date < day]
    if earlier.empty:
        return None
    regular = earlier[
        (earlier.index.time >= REGULAR_OPEN)
        & (earlier.index.time < REGULAR_CLOSE)
    ]
    if regular.empty:
        return None
    latest_day = max(regular.index.date)
    previous_session = regular.loc[regular.index.date == latest_day]
    if previous_session.empty:
        return None
    value = float(previous_session["Close"].iloc[-1])
    return value if np.isfinite(value) and value > 0 else None


def build_day_rows(ticker: str, history_through_day: pd.DataFrame):
    local = history_through_day.copy()
    local.index = local.index.tz_convert("America/New_York")
    day = max(local.index.date)
    current = local.loc[local.index.date == day]

    premarket = current[
        (current.index.time >= PREMARKET_START)
        & (current.index.time < REGULAR_OPEN)
    ]
    regular = current[
        (current.index.time >= REGULAR_OPEN)
        & (current.index.time < REGULAR_CLOSE)
    ]
    if premarket.empty or regular.empty:
        return []

    previous_close = previous_regular_close(local, day)
    if previous_close is None:
        return []

    open_price = float(regular["Open"].iloc[0])
    rows = []

    for snapshot_time in SNAPSHOT_TIMES:
        snapshot_at = pd.Timestamp.combine(day, snapshot_time).tz_localize("America/New_York")
        observed = premarket.loc[premarket.index <= snapshot_at]
        if len(observed) < 3:
            continue

        features = extract_predictive_features(
            observed,
            previous_close=previous_close,
            as_of=snapshot_at,
        )
        # Sparse-feed missing features are intentionally retained. The trainer
        # computes imputation values only from the training split and stores
        # them in the artifact for identical live inference behavior.
        present = sum(features.get(name) is not None for name in FEATURE_NAMES)
        if present < max(8, len(FEATURE_NAMES) // 2):
            continue

        current_price = float(observed["Close"].iloc[-1])
        threshold = edge_threshold_pct(features)
        row = {
            "ticker": ticker,
            "session_date": str(day),
            "snapshot_at": snapshot_at.tz_convert("UTC").isoformat(),
            "edge_threshold_pct": threshold,
            "feature_count_present": present,
            **features,
        }

        for minutes in PREMARKET_HORIZONS:
            target_at = snapshot_at + pd.Timedelta(minutes=minutes)
            if target_at.time() >= REGULAR_OPEN:
                row[f"label_premarket_{minutes}m"] = None
                continue
            future = close_at_or_after(
                premarket,
                target_at,
                max_delay_minutes=5,
            )
            ret = ((future / current_price) - 1.0) * 100.0 if future and current_price > 0 else None
            row[f"label_premarket_{minutes}m"] = label_return(ret, threshold)

        open_timestamp = regular.index[0]
        for minutes in OPEN_HORIZONS:
            target_at = open_timestamp + pd.Timedelta(minutes=minutes)
            future = close_at_or_after(
                regular,
                target_at,
                max_delay_minutes=2,
            )
            ret = ((future / open_price) - 1.0) * 100.0 if future and open_price > 0 else None
            row[f"label_open_{minutes}m"] = label_return(ret, threshold)

        rows.append(row)

    return rows


def main():
    parser = argparse.ArgumentParser(description="Build leakage-safe Orion premarket predictive training snapshots from raw minute OHLCV.")
    parser.add_argument("input", type=Path, help="CSV with ticker,timestamp,open,high,low,close,volume (UTC timestamps recommended)")
    parser.add_argument("--output", type=Path, default=Path("backend/data/premarket_training_dataset.csv"))
    args = parser.parse_args()

    raw = normalize_columns(pd.read_csv(args.input))
    raw["ny_date"] = raw["timestamp"].dt.tz_convert("America/New_York").dt.date
    rows = []

    for ticker, ticker_frame in raw.groupby("ticker", sort=False):
        ticker_frame = ticker_frame.sort_values("timestamp").set_index("timestamp")
        for day in sorted(ticker_frame["ny_date"].unique()):
            history_through_day = ticker_frame.loc[
                ticker_frame.index.tz_convert("America/New_York").date <= day
            ].drop(columns=["ny_date"])
            current_day = history_through_day.loc[
                history_through_day.index.tz_convert("America/New_York").date == day
            ]
            if current_day.empty:
                continue
            previous = history_through_day.loc[
                history_through_day.index.tz_convert("America/New_York").date < day
            ].tail(1200)
            combined = pd.concat([previous, current_day])
            rows.extend(build_day_rows(ticker, combined))

    dataset = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.output, index=False)
    print(f"Wrote {len(dataset):,} snapshots to {args.output}")
    if not dataset.empty:
        print(f"Tickers: {dataset['ticker'].nunique():,}; dates: {dataset['session_date'].nunique():,}")
        print(
            "Feature completeness: min/median/max = "
            f"{int(dataset['feature_count_present'].min())}/"
            f"{float(dataset['feature_count_present'].median()):.1f}/"
            f"{int(dataset['feature_count_present'].max())} of {len(FEATURE_NAMES)}"
        )
        for column in [column for column in dataset.columns if column.startswith("label_")]:
            counts = dataset[column].value_counts(dropna=False).to_dict()
            print(column, counts)


if __name__ == "__main__":
    main()
