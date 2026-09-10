from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from premarket_directional_v4_common import PREMARKET_TARGETS, V4_FEATURE_NAMES


MIN_TRAIN_DAYS = 40
CALIBRATION_DAYS = 10
TEST_DAYS = 5
MIN_REQUIRED_DAYS = MIN_TRAIN_DAYS + CALIBRATION_DAYS + TEST_DAYS
MIN_FEATURE_COMPLETENESS = 0.75
NY_TZ = "America/New_York"
REGULAR_OPEN_MINUTE = 9 * 60 + 30


def _safe_rate(mask: pd.Series | np.ndarray, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(np.asarray(mask, dtype=bool).sum()) / denominator, 6)


def _target_columns(target: str) -> tuple[str, str]:
    return f"future_return_{target}_pct", f"expected_sigma_{target}_pct"


def audit_dataset(frame: pd.DataFrame) -> dict:
    required_identity = ["ticker", "session_date", "snapshot_at", "minutes_to_open"]
    required_targets = [column for target in PREMARKET_TARGETS for column in _target_columns(target)]
    required = [*required_identity, *V4_FEATURE_NAMES, *required_targets]
    missing_columns = [column for column in required if column not in frame.columns]

    report = {
        "status": "FAIL",
        "rows": int(len(frame)),
        "tickers": 0,
        "sessions": 0,
        "required_sessions": MIN_REQUIRED_DAYS,
        "missing_columns": missing_columns,
        "checks": {},
        "targets": {},
        "blockers": [],
        "warnings": [],
    }
    if missing_columns:
        report["blockers"].append(
            "Missing columns required by Premarket Directional Engine v5: "
            + ", ".join(missing_columns)
        )
        return report

    work = frame.copy()
    work["ticker"] = work["ticker"].astype(str).str.upper().str.strip()
    work["session_date"] = pd.to_datetime(work["session_date"], errors="coerce").dt.date
    work["snapshot_at"] = pd.to_datetime(work["snapshot_at"], utc=True, errors="coerce")
    work["minutes_to_open"] = pd.to_numeric(work["minutes_to_open"], errors="coerce")

    invalid_identity = (
        work["ticker"].eq("")
        | work["session_date"].isna()
        | work["snapshot_at"].isna()
        | work["minutes_to_open"].isna()
    )
    invalid_identity_count = int(invalid_identity.sum())
    if invalid_identity_count:
        report["blockers"].append(f"{invalid_identity_count} rows have invalid identity/timestamp fields")

    valid = work.loc[~invalid_identity].copy()
    if valid.empty:
        report["blockers"].append("No valid rows remain after identity parsing")
        return report

    report["tickers"] = int(valid["ticker"].nunique())
    dates = sorted(valid["session_date"].unique())
    report["sessions"] = int(len(dates))

    duplicate_mask = valid.duplicated(["ticker", "session_date", "snapshot_at"], keep=False)
    duplicate_count = int(duplicate_mask.sum())
    report["checks"]["duplicate_ticker_snapshots"] = duplicate_count
    if duplicate_count:
        report["blockers"].append(f"{duplicate_count} rows belong to duplicate ticker/session/snapshot keys")

    local_snapshot = valid["snapshot_at"].dt.tz_convert(NY_TZ)
    local_minutes = local_snapshot.dt.hour * 60 + local_snapshot.dt.minute
    date_match = local_snapshot.dt.date == valid["session_date"]
    premarket_window = (local_minutes >= 4 * 60) & (local_minutes < REGULAR_OPEN_MINUTE)
    expected_minutes_to_open = REGULAR_OPEN_MINUTE - local_minutes
    minutes_match = np.isclose(
        valid["minutes_to_open"].to_numpy(dtype=float),
        expected_minutes_to_open.to_numpy(dtype=float),
        atol=0.01,
    )

    report["checks"]["snapshot_date_match_rate"] = _safe_rate(date_match, len(valid))
    report["checks"]["premarket_window_rate"] = _safe_rate(premarket_window, len(valid))
    report["checks"]["minutes_to_open_match_rate"] = _safe_rate(minutes_match, len(valid))
    if not bool(date_match.all()):
        report["blockers"].append("Some snapshot_at dates do not match session_date in America/New_York")
    if not bool(premarket_window.all()):
        report["blockers"].append("Some snapshot_at values are outside 04:00-09:29 America/New_York")
    if not bool(np.all(minutes_match)):
        report["blockers"].append("Some minutes_to_open values disagree with snapshot_at")

    feature_values = valid[V4_FEATURE_NAMES].apply(pd.to_numeric, errors="coerce")
    feature_fraction = feature_values.notna().mean(axis=1)
    report["checks"]["feature_completeness_median"] = round(float(feature_fraction.median()), 6)
    report["checks"]["feature_completeness_p10"] = round(float(feature_fraction.quantile(0.10)), 6)
    low_feature_rate = float((feature_fraction < MIN_FEATURE_COMPLETENESS).mean())
    report["checks"]["rows_below_feature_completeness_threshold_rate"] = round(low_feature_rate, 6)
    if low_feature_rate > 0.10:
        report["warnings"].append(
            f"{low_feature_rate:.1%} of rows have <{MIN_FEATURE_COMPLETENESS:.0%} v5 feature completeness"
        )

    report["checks"]["walk_forward_minimum_sessions_met"] = len(dates) >= MIN_REQUIRED_DAYS
    if len(dates) < MIN_REQUIRED_DAYS:
        report["blockers"].append(
            f"Only {len(dates)} distinct sessions; at least {MIN_REQUIRED_DAYS} are required for 40/10/5 validation"
        )

    ticker_sessions = valid[["ticker", "session_date"]].drop_duplicates().groupby("ticker").size()
    report["checks"]["median_sessions_per_ticker"] = round(float(ticker_sessions.median()), 3)
    report["checks"]["tickers_with_55_plus_sessions"] = int((ticker_sessions >= MIN_REQUIRED_DAYS).sum())
    if report["tickers"] > 1 and int((ticker_sessions >= MIN_REQUIRED_DAYS).sum()) == 0:
        report["warnings"].append("No individual ticker spans 55 sessions; cross-symbol generalization will dominate validation")

    for target in PREMARKET_TARGETS:
        return_col, sigma_col = _target_columns(target)
        returns = pd.to_numeric(valid[return_col], errors="coerce")
        sigma = pd.to_numeric(valid[sigma_col], errors="coerce")
        available = returns.notna()
        finite_returns = np.isfinite(returns.to_numpy(dtype=float, na_value=np.nan))
        positive_sigma = sigma > 0
        usable = available & finite_returns & positive_sigma

        target_report = {
            "rows": int(len(valid)),
            "returns_available": int(available.sum()),
            "usable_rows": int(usable.sum()),
            "usable_rate": round(float(usable.mean()), 6),
            "sessions_with_usable_rows": int(valid.loc[usable, "session_date"].nunique()),
            "nonpositive_sigma_with_return": int((available & ~positive_sigma).sum()),
        }

        if target.startswith("premarket_"):
            horizon = int(target.split("_")[1].removesuffix("m"))
            crosses_open = valid["minutes_to_open"] <= horizon
            leakage_rows = crosses_open & available
            target_report["cross_open_target_rows"] = int(leakage_rows.sum())
            if bool(leakage_rows.any()):
                report["blockers"].append(
                    f"{target}: {int(leakage_rows.sum())} target returns cross the regular-market open boundary"
                )

        if int((available & ~positive_sigma).sum()) > 0:
            report["blockers"].append(
                f"{target}: return labels exist with missing/non-positive expected sigma"
            )
        if target_report["sessions_with_usable_rows"] < MIN_REQUIRED_DAYS:
            report["blockers"].append(
                f"{target}: only {target_report['sessions_with_usable_rows']} sessions have usable labels; need {MIN_REQUIRED_DAYS}"
            )
        if target_report["usable_rate"] < 0.20:
            report["warnings"].append(
                f"{target}: only {target_report['usable_rate']:.1%} of rows have usable labels"
            )

        report["targets"][target] = target_report

    report["status"] = "PASS" if not report["blockers"] else "FAIL"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit an Orion premarket v2 dataset before leakage-safe v5 walk-forward validation."
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/models/premarket_dataset_readiness.json"),
    )
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset)
    report = audit_dataset(frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"Premarket dataset readiness: {report['status']} | rows={report['rows']} "
        f"tickers={report['tickers']} sessions={report['sessions']}"
    )
    for blocker in report["blockers"]:
        print(f"BLOCKER: {blocker}")
    for warning in report["warnings"]:
        print(f"WARNING: {warning}")
    print(f"Saved readiness report to {args.output}")
    raise SystemExit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
