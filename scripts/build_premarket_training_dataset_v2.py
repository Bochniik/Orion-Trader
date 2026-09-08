from __future__ import annotations

import argparse
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from build_premarket_training_dataset import (
    OPEN_HORIZONS,
    PREMARKET_HORIZONS,
    PREMARKET_START,
    REGULAR_CLOSE,
    REGULAR_OPEN,
    SNAPSHOT_TIMES,
    close_at_or_after,
    normalize_columns,
    previous_regular_close,
)

import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.premarket_predictive_engine import FEATURE_NAMES, extract_predictive_features


# Dataset v2 deliberately stores continuous future returns. Labels are retained
# only as a convenient diagnostic/default view; model selection is expected to
# tune the actionable threshold on validation data instead of treating these
# defaults as immutable truth.
DEFAULT_SIGMA_MULTIPLIER = 1.0
ABSOLUTE_MOVE_FLOOR_PCT = {
    5: 0.08,
    15: 0.12,
    30: 0.16,
    60: 0.22,
}


def horizon_sigma_pct(features: dict, horizon_minutes: int) -> float | None:
    """Estimate expected move scale for a horizon from recent minute volatility.

    ``realized_volatility_30m`` is the standard deviation of minute log returns
    expressed in percent. Under a square-root-of-time approximation, expected
    horizon sigma scales with sqrt(minutes). This is only target normalization,
    not a trading forecast.
    """
    rv = features.get("realized_volatility_30m")
    if rv is None:
        rv = features.get("realized_volatility_15m")
    try:
        rv = float(rv)
    except (TypeError, ValueError, OverflowError):
        return None
    if not np.isfinite(rv) or rv <= 0:
        return None
    return float(rv * sqrt(float(horizon_minutes)))


def horizon_edge_threshold_pct(features: dict, horizon_minutes: int) -> float:
    sigma = horizon_sigma_pct(features, horizon_minutes)
    floor = ABSOLUTE_MOVE_FLOOR_PCT.get(horizon_minutes, 0.12)
    if sigma is None:
        return float(floor)
    return float(max(floor, DEFAULT_SIGMA_MULTIPLIER * sigma))


def label_from_return(return_pct: float | None, threshold_pct: float) -> str | None:
    if return_pct is None or not np.isfinite(return_pct):
        return None
    if return_pct > threshold_pct:
        return "UP"
    if return_pct < -threshold_pct:
        return "DOWN"
    return "NO_EDGE"


def normalized_move(return_pct: float | None, sigma_pct: float | None) -> float | None:
    if return_pct is None or sigma_pct is None:
        return None
    if not np.isfinite(return_pct) or not np.isfinite(sigma_pct) or sigma_pct <= 0:
        return None
    return float(return_pct / sigma_pct)


def build_day_rows_v2(ticker: str, history_through_day: pd.DataFrame):
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
        present = sum(features.get(name) is not None for name in FEATURE_NAMES)
        if present < max(8, len(FEATURE_NAMES) // 2):
            continue

        current_price = float(observed["Close"].iloc[-1])
        row = {
            "ticker": ticker,
            "session_date": str(day),
            "snapshot_at": snapshot_at.tz_convert("UTC").isoformat(),
            "snapshot_time_et": snapshot_time.strftime("%H:%M"),
            "minutes_to_open": (9 * 60 + 30) - (snapshot_time.hour * 60 + snapshot_time.minute),
            "feature_count_present": present,
            "target_schema_version": "horizon_aware_continuous_v2",
            **features,
        }

        for minutes in PREMARKET_HORIZONS:
            target_at = snapshot_at + pd.Timedelta(minutes=minutes)
            if target_at.time() >= REGULAR_OPEN:
                future = None
            else:
                future = close_at_or_after(
                    premarket,
                    target_at,
                    max_delay_minutes=5,
                )

            ret = (
                ((future / current_price) - 1.0) * 100.0
                if future is not None and current_price > 0
                else None
            )
            sigma = horizon_sigma_pct(features, minutes)
            threshold = horizon_edge_threshold_pct(features, minutes)

            row[f"future_return_premarket_{minutes}m_pct"] = ret
            row[f"expected_sigma_premarket_{minutes}m_pct"] = sigma
            row[f"normalized_move_premarket_{minutes}m"] = normalized_move(ret, sigma)
            row[f"edge_threshold_premarket_{minutes}m_pct"] = threshold
            row[f"label_premarket_{minutes}m"] = label_from_return(ret, threshold)

        open_timestamp = regular.index[0]
        for minutes in OPEN_HORIZONS:
            target_at = open_timestamp + pd.Timedelta(minutes=minutes)
            future = close_at_or_after(
                regular,
                target_at,
                max_delay_minutes=2,
            )
            ret = (
                ((future / open_price) - 1.0) * 100.0
                if future is not None and open_price > 0
                else None
            )
            sigma = horizon_sigma_pct(features, minutes)
            threshold = horizon_edge_threshold_pct(features, minutes)
            row[f"future_return_open_{minutes}m_pct"] = ret
            row[f"expected_sigma_open_{minutes}m_pct"] = sigma
            row[f"normalized_move_open_{minutes}m"] = normalized_move(ret, sigma)
            row[f"edge_threshold_open_{minutes}m_pct"] = threshold
            row[f"label_open_{minutes}m"] = label_from_return(ret, threshold)

        rows.append(row)

    return rows


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Build Orion premarket training dataset v2 with horizon-aware thresholds "
            "and continuous future-return targets."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="CSV with ticker,timestamp,open,high,low,close,volume",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/premarket_training_dataset_v2.csv"),
    )
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
            rows.extend(build_day_rows_v2(ticker, combined))

    dataset = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.output, index=False)

    print(f"Wrote {len(dataset):,} v2 snapshots to {args.output}")
    if dataset.empty:
        return

    print(f"Tickers: {dataset['ticker'].nunique():,}; dates: {dataset['session_date'].nunique():,}")
    print(
        "Feature completeness: min/median/max = "
        f"{int(dataset['feature_count_present'].min())}/"
        f"{float(dataset['feature_count_present'].median()):.1f}/"
        f"{int(dataset['feature_count_present'].max())} of {len(FEATURE_NAMES)}"
    )

    for minutes in PREMARKET_HORIZONS:
        label_col = f"label_premarket_{minutes}m"
        return_col = f"future_return_premarket_{minutes}m_pct"
        threshold_col = f"edge_threshold_premarket_{minutes}m_pct"
        counts = dataset[label_col].value_counts(dropna=False).to_dict()
        usable = int(dataset[label_col].notna().sum())
        median_abs_return = float(dataset[return_col].abs().median(skipna=True))
        median_threshold = float(dataset[threshold_col].median(skipna=True))
        print(
            f"{label_col} usable={usable}/{len(dataset)} {counts}; "
            f"median_abs_return={median_abs_return:.4f}% "
            f"median_threshold={median_threshold:.4f}%"
        )


if __name__ == "__main__":
    main()
