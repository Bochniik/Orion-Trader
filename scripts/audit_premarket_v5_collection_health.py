from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
RUNNER_VERSION = "premarket-v5-cloud-shadow-v2"
REPORT_CONTRACT = "orion-premarket-v5-collection-health-v1"
SUPPORTED_HORIZONS = ("premarket_5m", "premarket_15m", "premarket_30m")
SNAPSHOT_CLOCKS = {
    "early": (6, 45),
    "mid": (8, 0),
    "late": (9, 15),
}


class CollectionHealthError(ValueError):
    pass


def _fraction(observed: int, expected: int) -> float | None:
    if expected <= 0:
        return None
    return round(observed / expected, 6)


def _parse_as_of_et(value: Any) -> datetime:
    if not value:
        raise CollectionHealthError("as_of_et is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CollectionHealthError("as_of_et must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CollectionHealthError("as_of_et must be timezone-aware")
    local = parsed.astimezone(NY)
    if local.weekday() >= 5:
        raise CollectionHealthError("premarket collection artifact cannot belong to a weekend")
    return local


def _snapshot_from_clock(local: datetime) -> str:
    clock = (local.hour, local.minute)
    for snapshot, expected in SNAPSHOT_CLOCKS.items():
        if clock == expected:
            return snapshot
    raise CollectionHealthError(
        f"as_of_et {local.isoformat()} is not on the preregistered early/mid/late cadence"
    )


def _validate_projection(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("runner_version") != RUNNER_VERSION:
        raise CollectionHealthError("unexpected Premarket V5 runner_version")
    if payload.get("mode") != "shadow_research_only":
        raise CollectionHealthError("artifact is not shadow_research_only")
    if payload.get("order_submission_enabled") is not False:
        raise CollectionHealthError("order_submission_enabled must be false")
    if payload.get("causal_cutoff_enforced") is not True:
        raise CollectionHealthError("causal_cutoff_enforced must be true")

    local = _parse_as_of_et(payload.get("as_of_et"))
    snapshot = _snapshot_from_clock(local)

    symbols = payload.get("symbols")
    predictions = payload.get("predictions")
    if not isinstance(symbols, list) or not isinstance(predictions, list):
        raise CollectionHealthError("artifact is missing symbols/predictions lists")

    normalized_symbols = [str(symbol).upper() for symbol in symbols]
    if not normalized_symbols:
        raise CollectionHealthError("symbols must not be empty")
    if len(normalized_symbols) != len(set(normalized_symbols)):
        raise CollectionHealthError("symbols contains duplicates")

    prediction_by_symbol: dict[str, dict[str, Any]] = {}
    for row in predictions:
        if not isinstance(row, dict):
            raise CollectionHealthError("predictions entries must be objects")
        ticker = str(row.get("ticker", "")).upper()
        if ticker not in normalized_symbols:
            raise CollectionHealthError("predictions contains an unexpected ticker")
        if ticker in prediction_by_symbol:
            raise CollectionHealthError("predictions contains duplicate tickers")
        prediction_by_symbol[ticker] = row

    if set(prediction_by_symbol) != set(normalized_symbols):
        raise CollectionHealthError("predictions must contain exactly one row per requested symbol")

    missing_pairs: list[dict[str, str]] = []
    available_symbol_count = 0
    unavailable_reasons: Counter[str] = Counter()
    for symbol in normalized_symbols:
        row = prediction_by_symbol[symbol]
        if row.get("available") is not True:
            reason = str(row.get("reason") or "unspecified")
            unavailable_reasons[reason] += 1
            for horizon in SUPPORTED_HORIZONS:
                missing_pairs.append({"symbol": symbol, "horizon": horizon})
            continue

        available_symbol_count += 1
        forecasts = row.get("forecasts")
        if not isinstance(forecasts, dict):
            raise CollectionHealthError("available prediction is missing forecasts")
        for horizon in SUPPORTED_HORIZONS:
            if not isinstance(forecasts.get(horizon), dict):
                missing_pairs.append({"symbol": symbol, "horizon": horizon})

    expected_pair_count = len(normalized_symbols) * len(SUPPORTED_HORIZONS)
    observed_pair_count = expected_pair_count - len(missing_pairs)
    return {
        "session": local.date().isoformat(),
        "as_of_et": local.isoformat(),
        "snapshot": snapshot,
        "symbols": sorted(normalized_symbols),
        "symbol_count": len(normalized_symbols),
        "available_symbol_count": available_symbol_count,
        "unavailable_symbol_count": len(normalized_symbols) - available_symbol_count,
        "unavailable_reasons": dict(sorted(unavailable_reasons.items())),
        "expected_pair_count": expected_pair_count,
        "observed_pair_count": observed_pair_count,
        "missing_pairs": sorted(missing_pairs, key=lambda row: (row["horizon"], row["symbol"])),
    }


def _canonical_projection_digest(projections: list[dict[str, Any]]) -> str:
    canonical = json.dumps(projections, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_health_report(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    projections = [_validate_projection(payload) for payload in payloads]
    projections.sort(key=lambda row: (row["as_of_et"], row["snapshot"], tuple(row["symbols"])))

    duplicate_keys = Counter((row["session"], row["snapshot"]) for row in projections)
    duplicates = [f"{session}:{snapshot}" for (session, snapshot), count in duplicate_keys.items() if count > 1]
    if duplicates:
        raise CollectionHealthError(f"duplicate session/snapshot artifacts: {','.join(sorted(duplicates))}")

    sessions = sorted({row["session"] for row in projections})
    expected_total = sum(row["expected_pair_count"] for row in projections)
    observed_total = sum(row["observed_pair_count"] for row in projections)

    missing_by_symbol: Counter[str] = Counter()
    unavailable_reasons: Counter[str] = Counter()
    for row in projections:
        unavailable_reasons.update(row["unavailable_reasons"])
        for pair in row["missing_pairs"]:
            missing_by_symbol[pair["symbol"]] += 1

    by_snapshot: dict[str, dict[str, Any]] = {}
    for snapshot in SNAPSHOT_CLOCKS:
        rows = [row for row in projections if row["snapshot"] == snapshot]
        expected = sum(row["expected_pair_count"] for row in rows)
        observed = sum(row["observed_pair_count"] for row in rows)
        by_snapshot[snapshot] = {
            "artifact_count": len(rows),
            "distinct_session_count": len({row["session"] for row in rows}),
            "expected_pair_count": expected,
            "observed_pair_count": observed,
            "missing_pair_count": expected - observed,
            "coverage_fraction": _fraction(observed, expected),
        }

    by_horizon: dict[str, dict[str, Any]] = {}
    for horizon in SUPPORTED_HORIZONS:
        expected = 0
        observed = 0
        for row in projections:
            expected += row["symbol_count"]
            missing = sum(1 for pair in row["missing_pairs"] if pair["horizon"] == horizon)
            observed += row["symbol_count"] - missing
        by_horizon[horizon] = {
            "expected_pair_count": expected,
            "observed_pair_count": observed,
            "missing_pair_count": expected - observed,
            "coverage_fraction": _fraction(observed, expected),
        }

    complete_artifacts = sum(1 for row in projections if row["expected_pair_count"] == row["observed_pair_count"])
    return {
        "contract": REPORT_CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "artifact_count": len(projections),
        "complete_artifact_count": complete_artifacts,
        "degraded_artifact_count": len(projections) - complete_artifacts,
        "distinct_session_count": len(sessions),
        "sessions": sessions,
        "coverage": {
            "expected_pair_count": expected_total,
            "observed_pair_count": observed_total,
            "missing_pair_count": expected_total - observed_total,
            "coverage_fraction": _fraction(observed_total, expected_total),
            "by_snapshot": by_snapshot,
            "by_horizon": by_horizon,
            "missing_by_symbol": dict(sorted(missing_by_symbol.items())),
            "unavailable_reasons": dict(sorted(unavailable_reasons.items())),
        },
        "operational_projection_sha256": _canonical_projection_digest(projections),
    }


def _load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CollectionHealthError(f"{path}: prediction artifact must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a score-blind operational health report for Premarket V5 cloud-shadow artifacts."
    )
    parser.add_argument("--input", nargs="+", type=Path, required=True, help="Premarket V5 prediction JSON artifacts")
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
        "distinct_session_count": report["distinct_session_count"],
        "coverage_fraction": report["coverage"]["coverage_fraction"],
        "by_snapshot": report["coverage"]["by_snapshot"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
