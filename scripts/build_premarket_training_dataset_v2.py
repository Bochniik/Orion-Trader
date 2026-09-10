from __future__ import annotations

import argparse
import hashlib
import json
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


DATASET_BUILDER_VERSION = "premarket-training-dataset-v2-lineage-1"
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_manifest_path(input_path: Path) -> Path:
    return input_path.with_suffix(input_path.suffix + ".manifest.json")


def verify_source_lineage(input_path: Path) -> dict:
    """Return source identity and fail closed when an existing manifest disagrees.

    Collector manifests are optional for backwards compatibility, but when one
    is present its content-addressed CSV identity must match the exact input
    bytes used by this builder.  This prevents a resumed/replaced raw CSV from
    silently inheriting stale provenance.
    """
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    raw_sha256 = file_sha256(input_path)
    manifest_path = source_manifest_path(input_path)
    if not manifest_path.exists():
        return {
            "status": "unverified_no_source_manifest",
            "source_csv_sha256": raw_sha256,
            "source_manifest_path": None,
            "source_manifest_sha256": None,
            "source_manifest": None,
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid source manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Source manifest must contain a JSON object: {manifest_path}")

    declared_sha256 = str(manifest.get("csv_sha256") or "").strip().lower()
    if not declared_sha256:
        raise ValueError(f"Source manifest is missing csv_sha256: {manifest_path}")
    if declared_sha256 != raw_sha256:
        raise ValueError(
            "Source CSV SHA-256 does not match its collection manifest: "
            f"declared={declared_sha256} actual={raw_sha256}"
        )

    return {
        "status": "verified_source_manifest",
        "source_csv_sha256": raw_sha256,
        "source_manifest_path": str(manifest_path),
        "source_manifest_sha256": file_sha256(manifest_path),
        "source_manifest": manifest,
    }


def write_dataset_manifest(
    output: Path,
    *,
    input_path: Path,
    lineage: dict,
    dataset: pd.DataFrame,
) -> Path:
    if not output.exists():
        raise FileNotFoundError(output)

    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    payload = {
        "builder_version": DATASET_BUILDER_VERSION,
        "target_schema_version": "horizon_aware_continuous_v2",
        "source_path": str(input_path),
        "source_lineage_status": lineage["status"],
        "source_csv_sha256": lineage["source_csv_sha256"],
        "source_manifest_path": lineage["source_manifest_path"],
        "source_manifest_sha256": lineage["source_manifest_sha256"],
        "dataset_csv_sha256": file_sha256(output),
        "row_count": int(len(dataset)),
        "ticker_count": int(dataset["ticker"].nunique()) if "ticker" in dataset.columns else 0,
        "session_count": int(dataset["session_date"].nunique()) if "session_date" in dataset.columns else 0,
        "schema": [str(column) for column in dataset.columns],
        "feature_names": list(FEATURE_NAMES),
        "premarket_horizons_minutes": list(PREMARKET_HORIZONS),
        "open_horizons_minutes": list(OPEN_HORIZONS),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


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

    lineage = verify_source_lineage(args.input)
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
    manifest_path = write_dataset_manifest(
        args.output,
        input_path=args.input,
        lineage=lineage,
        dataset=dataset,
    )

    print(f"Wrote {len(dataset):,} v2 snapshots to {args.output}")
    print(f"Dataset lineage manifest: {manifest_path} ({lineage['status']})")
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
