from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

PREDICTION_CONTRACT = "orion-long-horizon-v5-paired-shadow-v1"
REPORT_CONTRACT = "orion-long-horizon-v5-collection-health-v1"
SUPPORTED_HORIZONS = ("3h", "5h")


class CollectionHealthError(ValueError):
    pass


def _fraction(observed: int, expected: int) -> float | None:
    if expected <= 0:
        return None
    return round(observed / expected, 6)


def _parse_session(value: Any) -> str:
    if not value:
        raise CollectionHealthError("session_gate.as_of_et is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CollectionHealthError("session_gate.as_of_et must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CollectionHealthError("session_gate.as_of_et must be timezone-aware")
    return parsed.date().isoformat()


def _validate_projection(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("contract") != PREDICTION_CONTRACT:
        raise CollectionHealthError("unexpected prediction contract")

    status = payload.get("status")
    if status not in {"completed", "degraded", "skipped"}:
        raise CollectionHealthError("unexpected prediction status")

    gate = payload.get("session_gate")
    coverage = payload.get("coverage")
    symbols = payload.get("symbols_requested")
    if not isinstance(gate, dict) or not isinstance(coverage, dict) or not isinstance(symbols, list):
        raise CollectionHealthError("prediction artifact is missing operational coverage metadata")
    if coverage.get("score_blind") is not True:
        raise CollectionHealthError("coverage metadata must be score-blind")

    eligible_horizons = gate.get("eligible_horizons")
    missing_pairs = coverage.get("missing_pairs")
    if not isinstance(eligible_horizons, list) or not isinstance(missing_pairs, list):
        raise CollectionHealthError("invalid operational coverage lists")
    unknown = sorted(set(map(str, eligible_horizons)) - set(SUPPORTED_HORIZONS))
    if unknown:
        raise CollectionHealthError(f"unsupported eligible horizons: {','.join(unknown)}")

    normalized_symbols = [str(symbol).upper() for symbol in symbols]
    if len(normalized_symbols) != len(set(normalized_symbols)):
        raise CollectionHealthError("symbols_requested contains duplicates")

    expected_pairs = {(symbol, str(horizon)) for symbol in normalized_symbols for horizon in eligible_horizons}
    normalized_missing: list[tuple[str, str]] = []
    for row in missing_pairs:
        if not isinstance(row, dict):
            raise CollectionHealthError("missing_pairs entries must be objects")
        pair = (str(row.get("symbol", "")).upper(), str(row.get("horizon", "")))
        if pair not in expected_pairs:
            raise CollectionHealthError("missing_pairs contains an unexpected symbol/horizon")
        normalized_missing.append(pair)
    if len(normalized_missing) != len(set(normalized_missing)):
        raise CollectionHealthError("missing_pairs contains duplicates")

    expected_count = int(coverage.get("expected_pair_count", -1))
    observed_count = int(coverage.get("observed_pair_count", -1))
    if expected_count != len(expected_pairs):
        raise CollectionHealthError("expected_pair_count disagrees with requested symbol/horizon geometry")
    if observed_count != expected_count - len(normalized_missing):
        raise CollectionHealthError("observed_pair_count disagrees with missing_pairs")
    if bool(coverage.get("complete")) != (not normalized_missing):
        raise CollectionHealthError("coverage.complete disagrees with missing_pairs")
    if status == "completed" and normalized_missing:
        raise CollectionHealthError("completed run cannot contain missing pairs")
    if status == "degraded" and not normalized_missing:
        raise CollectionHealthError("degraded run must contain missing pairs")
    if status == "skipped" and expected_count != 0:
        raise CollectionHealthError("skipped run cannot expect prediction pairs")

    return {
        "status": status,
        "session": _parse_session(gate.get("as_of_et")),
        "as_of_et": str(gate.get("as_of_et")),
        "eligible_horizons": sorted(map(str, eligible_horizons)),
        "skip_reason": gate.get("reason") if status == "skipped" else None,
        "symbols": sorted(normalized_symbols),
        "expected_pair_count": expected_count,
        "observed_pair_count": observed_count,
        "missing_pairs": [
            {"symbol": symbol, "horizon": horizon}
            for symbol, horizon in sorted(normalized_missing)
        ],
    }


def _canonical_projection_digest(projections: list[dict[str, Any]]) -> str:
    canonical = json.dumps(projections, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_health_report(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    projections = [_validate_projection(payload) for payload in payloads]
    projections.sort(key=lambda row: (row["as_of_et"], row["status"], tuple(row["symbols"])))

    status_counts = Counter(row["status"] for row in projections)
    skip_reasons = Counter(str(row["skip_reason"]) for row in projections if row["skip_reason"])
    eligible = [row for row in projections if row["expected_pair_count"] > 0]
    sessions = sorted({row["session"] for row in eligible})

    by_horizon: dict[str, dict[str, Any]] = {}
    missing_by_symbol: Counter[str] = Counter()
    for horizon in SUPPORTED_HORIZONS:
        expected = 0
        missing = 0
        eligible_runs = 0
        complete_runs = 0
        for row in projections:
            if horizon not in row["eligible_horizons"]:
                continue
            eligible_runs += 1
            expected += len(row["symbols"])
            horizon_missing = [pair for pair in row["missing_pairs"] if pair["horizon"] == horizon]
            missing += len(horizon_missing)
            if not horizon_missing:
                complete_runs += 1
            for pair in horizon_missing:
                missing_by_symbol[pair["symbol"]] += 1
        observed = expected - missing
        by_horizon[horizon] = {
            "eligible_run_count": eligible_runs,
            "complete_run_count": complete_runs,
            "expected_pair_count": expected,
            "observed_pair_count": observed,
            "missing_pair_count": missing,
            "coverage_fraction": _fraction(observed, expected),
        }

    expected_total = sum(row["expected_pair_count"] for row in projections)
    observed_total = sum(row["observed_pair_count"] for row in projections)
    missing_total = expected_total - observed_total
    five_hour = by_horizon["5h"]

    return {
        "contract": REPORT_CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "artifact_count": len(projections),
        "eligible_run_count": len(eligible),
        "complete_run_count": status_counts["completed"],
        "degraded_run_count": status_counts["degraded"],
        "skipped_run_count": status_counts["skipped"],
        "distinct_session_count": len(sessions),
        "sessions": sessions,
        "coverage": {
            "expected_pair_count": expected_total,
            "observed_pair_count": observed_total,
            "missing_pair_count": missing_total,
            "coverage_fraction": _fraction(observed_total, expected_total),
            "by_horizon": by_horizon,
            "missing_by_symbol": dict(sorted(missing_by_symbol.items())),
        },
        "critical_5h": {
            "eligible_run_count": five_hour["eligible_run_count"],
            "complete_run_count": five_hour["complete_run_count"],
            "expected_pair_count": five_hour["expected_pair_count"],
            "observed_pair_count": five_hour["observed_pair_count"],
            "missing_pair_count": five_hour["missing_pair_count"],
            "coverage_fraction": five_hour["coverage_fraction"],
        },
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "operational_projection_sha256": _canonical_projection_digest(projections),
    }


def _load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CollectionHealthError(f"{path}: prediction artifact must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a score-blind operational health report for long-horizon V5 collection artifacts.")
    parser.add_argument("--input", nargs="+", type=Path, required=True, help="Paired prediction JSON artifacts")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        report = build_health_report(_load_payload(path) for path in args.input)
    except (OSError, json.JSONDecodeError, CollectionHealthError, ValueError) as exc:
        print(json.dumps({"status": "invalid_collection_health_input", "error": str(exc)}, sort_keys=True))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "score_blind": True,
        "metrics_exposed": False,
        "artifact_count": report["artifact_count"],
        "coverage_fraction": report["coverage"]["coverage_fraction"],
        "critical_5h_coverage_fraction": report["critical_5h"]["coverage_fraction"],
        "degraded_run_count": report["degraded_run_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
