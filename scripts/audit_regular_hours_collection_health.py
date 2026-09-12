from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.nyse_session_calendar import is_nyse_trading_day

NY = ZoneInfo("America/New_York")
RUNNER_VERSION = "regular-hours-v3-1-cloud-shadow-v2"
LEGACY_RUNNER_VERSIONS = {"regular-hours-v3-1-cloud-shadow-v1"}
REPORT_CONTRACT = "orion-regular-hours-collection-health-v1"
PREREGISTERED_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")


class CollectionHealthError(ValueError):
    pass


def _fraction(observed: int, expected: int) -> float | None:
    if expected <= 0:
        return None
    return round(observed / expected, 6)


def _parse_as_of_et(value: Any) -> datetime:
    if not value:
        raise CollectionHealthError("session_gate.as_of_et is required")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CollectionHealthError("session_gate.as_of_et must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CollectionHealthError("session_gate.as_of_et must be timezone-aware")
    return parsed.astimezone(NY)


def _validate_common(payload: dict[str, Any]) -> tuple[datetime, str]:
    if payload.get("runner_version") != RUNNER_VERSION:
        raise CollectionHealthError("unexpected regular-hours runner_version")
    if payload.get("research_only") is not True:
        raise CollectionHealthError("artifact must be research_only")
    if payload.get("order_submission_enabled") is not False:
        raise CollectionHealthError("order_submission_enabled must be false")
    if payload.get("runtime_modified") is not False:
        raise CollectionHealthError("runtime_modified must be false")

    gate = payload.get("session_gate")
    if not isinstance(gate, dict):
        raise CollectionHealthError("session_gate must be an object")
    local = _parse_as_of_et(gate.get("as_of_et"))
    status = str(payload.get("status") or "")
    if status not in {"completed", "skipped"}:
        raise CollectionHealthError(f"unsupported artifact status: {status or 'missing'}")
    return local, status


def _legacy_projection(payload: dict[str, Any]) -> dict[str, Any]:
    version = str(payload.get("runner_version") or "")
    if version not in LEGACY_RUNNER_VERSIONS:
        raise CollectionHealthError("unexpected regular-hours runner_version")
    if payload.get("research_only") is not True or payload.get("order_submission_enabled") is not False:
        raise CollectionHealthError("legacy artifact must remain research-only with order submission disabled")
    gate = payload.get("session_gate")
    if not isinstance(gate, dict):
        raise CollectionHealthError("legacy artifact session_gate must be an object")
    local = _parse_as_of_et(gate.get("as_of_et"))
    return {
        "session": local.date().isoformat(),
        "as_of_et": local.isoformat(),
        "status": "legacy_excluded",
        "runner_version": version,
        "standard_universe": False,
    }


def _validate_projection(payload: dict[str, Any]) -> dict[str, Any]:
    version = str(payload.get("runner_version") or "")
    if version in LEGACY_RUNNER_VERSIONS:
        return _legacy_projection(payload)

    local, status = _validate_common(payload)
    gate = payload["session_gate"]
    session = local.date().isoformat()

    if status == "skipped":
        if gate.get("allowed") is not False:
            raise CollectionHealthError("skipped artifact must have session_gate.allowed=false")
        return {
            "session": session,
            "as_of_et": local.isoformat(),
            "status": status,
            "skip_reason": str(payload.get("reason") or gate.get("reason") or "unspecified"),
            "standard_universe": False,
        }

    if gate.get("allowed") is not True:
        raise CollectionHealthError("completed artifact must have session_gate.allowed=true")
    if local.weekday() >= 5 or not is_nyse_trading_day(local.date()):
        raise CollectionHealthError("completed artifact must belong to a NYSE trading session")

    requested = payload.get("symbols_requested")
    results = payload.get("results")
    if not isinstance(requested, list) or not isinstance(results, dict):
        raise CollectionHealthError("completed artifact is missing symbols_requested/results")

    symbols = [str(symbol).upper() for symbol in requested]
    if not symbols or len(symbols) != len(set(symbols)):
        raise CollectionHealthError("symbols_requested must be a non-empty unique list")

    symbol_rows = results.get("symbols")
    failures = results.get("failures")
    if not isinstance(symbol_rows, dict) or not isinstance(failures, dict):
        raise CollectionHealthError("results.symbols/failures must be objects")

    unexpected = (set(symbol_rows) | set(failures)) - set(symbols)
    if unexpected:
        raise CollectionHealthError("results contain symbols not present in symbols_requested")
    missing = set(symbols) - (set(symbol_rows) | set(failures))
    if missing:
        raise CollectionHealthError("requested symbols are missing from both results.symbols and results.failures")

    available = 0
    provenance_valid = 0
    retry_symbols = 0
    alignment_attempts = 0
    for symbol in symbols:
        row = symbol_rows.get(symbol)
        if row is None:
            continue
        if not isinstance(row, dict):
            raise CollectionHealthError("results.symbols entries must be objects")
        if row.get("available") is True:
            available += 1
        if row.get("source_timestamp_aligned") is True and bool(row.get("as_of")):
            provenance_valid += 1
        attempts = int(row.get("alignment_attempts") or 1)
        if attempts < 1:
            raise CollectionHealthError("alignment_attempts must be >= 1")
        alignment_attempts += attempts
        if attempts > 1:
            retry_symbols += 1

    failure_count = len(failures)
    recomputed = {
        "symbol_count": len(symbols),
        "available_symbol_count": available,
        "provenance_valid_symbol_count": provenance_valid,
        "alignment_retry_symbol_count": retry_symbols,
        "alignment_attempt_count": alignment_attempts,
        "failure_count": failure_count,
    }
    for key, expected in recomputed.items():
        if key in results and int(results.get(key) or 0) != expected:
            raise CollectionHealthError(f"reported {key} does not match recomputed operational projection")

    return {
        "session": session,
        "as_of_et": local.isoformat(),
        "status": status,
        "standard_universe": set(symbols) == set(PREREGISTERED_SYMBOLS) and len(symbols) == len(PREREGISTERED_SYMBOLS),
        **recomputed,
    }


def _canonical_projection_digest(projections: list[dict[str, Any]]) -> str:
    canonical = json.dumps(projections, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _aggregate_completed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    requested = sum(int(row["symbol_count"]) for row in rows)
    available = sum(int(row["available_symbol_count"]) for row in rows)
    provenance_valid = sum(int(row["provenance_valid_symbol_count"]) for row in rows)
    failures = sum(int(row["failure_count"]) for row in rows)
    retries = sum(int(row["alignment_retry_symbol_count"]) for row in rows)
    attempts = sum(int(row["alignment_attempt_count"]) for row in rows)
    return {
        "requested_symbol_count": requested,
        "available_symbol_count": available,
        "provenance_valid_symbol_count": provenance_valid,
        "provenance_gap_symbol_count": requested - provenance_valid,
        "failure_count": failures,
        "alignment_retry_symbol_count": retries,
        "alignment_attempt_count": attempts,
        "available_fraction": _fraction(available, requested),
        "provenance_valid_fraction": _fraction(provenance_valid, requested),
        "failure_fraction": _fraction(failures, requested),
        "alignment_retry_fraction": _fraction(retries, requested),
        "mean_alignment_attempts_per_requested_symbol": round(attempts / requested, 6) if requested else None,
    }


def build_health_report(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    projections = [_validate_projection(payload) for payload in payloads]
    projections.sort(key=lambda row: (row["as_of_et"], row["status"]))

    completed = [row for row in projections if row["status"] == "completed"]
    standard = [row for row in completed if row["standard_universe"]]
    nonstandard = [row for row in completed if not row["standard_universe"]]
    skipped = [row for row in projections if row["status"] == "skipped"]
    legacy = [row for row in projections if row["status"] == "legacy_excluded"]

    skip_reasons = Counter(row["skip_reason"] for row in skipped)
    legacy_versions = Counter(row["runner_version"] for row in legacy)
    sessions = sorted({row["session"] for row in standard})

    by_session: dict[str, dict[str, Any]] = {}
    for session in sessions:
        rows = [row for row in standard if row["session"] == session]
        by_session[session] = {
            "artifact_count": len(rows),
            **_aggregate_completed(rows),
        }

    return {
        "contract": REPORT_CONTRACT,
        "score_blind": True,
        "metrics_exposed": False,
        "artifact_count": len(projections),
        "completed_artifact_count": len(completed),
        "standard_universe_artifact_count": len(standard),
        "nonstandard_universe_artifact_count": len(nonstandard),
        "skipped_artifact_count": len(skipped),
        "legacy_excluded_artifact_count": len(legacy),
        "legacy_excluded_runner_versions": dict(sorted(legacy_versions.items())),
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "distinct_standard_session_count": len(sessions),
        "sessions": sessions,
        "coverage": _aggregate_completed(standard),
        "by_session": by_session,
        "operational_projection_sha256": _canonical_projection_digest(projections),
    }


def _load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CollectionHealthError(f"{path}: prediction artifact must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit regular-hours V3.1 cloud-shadow collection health without inspecting predictive scores."
    )
    parser.add_argument("predictions", nargs="*", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/cloud_shadow/regular_hours_v3_1/collection-health.json"),
    )
    args = parser.parse_args()

    report = build_health_report(_load_payload(path) for path in args.predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
