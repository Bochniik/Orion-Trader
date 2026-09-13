from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any, Iterable

CONTRACT = "orion-long-horizon-v5-paired-shadow-v1"
SUMMARY_CONTRACT = "orion-long-horizon-v5-collection-health-v3"
SUPPORTED_STATUSES = {"completed", "degraded", "skipped"}
SUPPORTED_HORIZONS = {"3h", "5h"}


def _reason_category(reason: Any) -> str:
    text = str(reason or "unknown_failure").strip()
    if not text:
        return "unknown_failure"
    return text.split(":", 1)[0].strip() or "unknown_failure"


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    if payload.get("contract") != CONTRACT:
        raise ValueError(f"{path}: unexpected contract {payload.get('contract')!r}")
    return payload


def _is_forward_eligible(payload: dict[str, Any]) -> bool:
    provenance = payload.get("acquisition_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("acquisition_provenance must be a JSON object")
    value = provenance.get("forward_eligible")
    if not isinstance(value, bool):
        raise ValueError("acquisition_provenance.forward_eligible must be boolean")
    return value


def _strict_nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _validated_forward_projection(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    if status not in SUPPORTED_STATUSES:
        raise ValueError(f"unexpected forward run status: {status!r}")

    symbols = payload.get("symbols_requested")
    gate = payload.get("session_gate")
    coverage = payload.get("coverage")
    failures = payload.get("failures")
    if not isinstance(symbols, list):
        raise ValueError("symbols_requested must be a JSON array")
    if not isinstance(gate, dict):
        raise ValueError("session_gate must be a JSON object")
    if not isinstance(coverage, dict):
        raise ValueError("coverage must be a JSON object")
    if not isinstance(failures, dict):
        raise ValueError("failures must be a JSON object")
    if coverage.get("score_blind") is not True:
        raise ValueError("coverage.score_blind must be true")

    normalized_symbols = [str(symbol).strip().upper() for symbol in symbols]
    if any(not symbol for symbol in normalized_symbols):
        raise ValueError("symbols_requested cannot contain empty symbols")
    if len(normalized_symbols) != len(set(normalized_symbols)):
        raise ValueError("symbols_requested contains duplicates")

    eligible_horizons = gate.get("eligible_horizons")
    if not isinstance(eligible_horizons, list):
        raise ValueError("session_gate.eligible_horizons must be a JSON array")
    normalized_horizons = [str(horizon) for horizon in eligible_horizons]
    unknown_horizons = sorted(set(normalized_horizons) - SUPPORTED_HORIZONS)
    if unknown_horizons:
        raise ValueError(f"unsupported eligible horizons: {','.join(unknown_horizons)}")
    if len(normalized_horizons) != len(set(normalized_horizons)):
        raise ValueError("session_gate.eligible_horizons contains duplicates")

    expected_geometry = {
        (symbol, horizon)
        for symbol in normalized_symbols
        for horizon in normalized_horizons
    }
    missing_pairs_raw = coverage.get("missing_pairs")
    if not isinstance(missing_pairs_raw, list):
        raise ValueError("coverage.missing_pairs must be a JSON array")
    missing_pairs: list[tuple[str, str]] = []
    for row in missing_pairs_raw:
        if not isinstance(row, dict):
            raise ValueError("coverage.missing_pairs entries must be JSON objects")
        pair = (
            str(row.get("symbol", "")).strip().upper(),
            str(row.get("horizon", "")),
        )
        if pair not in expected_geometry:
            raise ValueError("coverage.missing_pairs contains an unexpected symbol/horizon")
        missing_pairs.append(pair)
    if len(missing_pairs) != len(set(missing_pairs)):
        raise ValueError("coverage.missing_pairs contains duplicates")

    expected = _strict_nonnegative_int(coverage.get("expected_pair_count"), "coverage.expected_pair_count")
    observed = _strict_nonnegative_int(coverage.get("observed_pair_count"), "coverage.observed_pair_count")
    if expected != len(expected_geometry):
        raise ValueError("coverage.expected_pair_count disagrees with symbol/horizon geometry")
    if observed != expected - len(missing_pairs):
        raise ValueError("coverage.observed_pair_count disagrees with coverage.missing_pairs")

    complete = coverage.get("complete")
    if not isinstance(complete, bool):
        raise ValueError("coverage.complete must be boolean")
    if complete != (len(missing_pairs) == 0):
        raise ValueError("coverage.complete disagrees with coverage.missing_pairs")
    if status == "completed" and not complete:
        raise ValueError("completed run must have complete coverage")
    if status == "degraded" and complete:
        raise ValueError("degraded run must have incomplete coverage")
    if status == "skipped" and expected != 0:
        raise ValueError("skipped run cannot expect prediction pairs")

    normalized_failures: dict[str, Any] = {}
    for symbol, reason in failures.items():
        normalized_symbol = str(symbol).strip().upper()
        if normalized_symbol not in set(normalized_symbols):
            raise ValueError("failures contains a symbol outside symbols_requested")
        normalized_failures[normalized_symbol] = reason

    return {
        "status": status,
        "expected_pair_count": expected,
        "observed_pair_count": observed,
        "complete": complete,
        "failures": normalized_failures,
    }


def summarize_payloads(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    symbols_by_reason: dict[str, set[str]] = defaultdict(set)
    input_run_count = 0
    forward_eligible_runs = 0
    ignored_non_forward_runs = 0
    complete_runs = 0
    expected_pairs = 0
    observed_pairs = 0

    for payload in payloads:
        input_run_count += 1
        if not _is_forward_eligible(payload):
            ignored_non_forward_runs += 1
            continue

        projection = _validated_forward_projection(payload)
        forward_eligible_runs += 1
        status_counts[projection["status"]] += 1
        expected_pairs += projection["expected_pair_count"]
        observed_pairs += projection["observed_pair_count"]
        if projection["complete"]:
            complete_runs += 1

        for symbol, reason in projection["failures"].items():
            category = _reason_category(reason)
            reason_counts[category] += 1
            symbols_by_reason[category].add(symbol)

    coverage_rate = None
    if expected_pairs > 0:
        coverage_rate = round(observed_pairs / expected_pairs, 6)

    return {
        "contract": SUMMARY_CONTRACT,
        "score_blind": True,
        "population": "forward_eligible_only",
        "input_run_count": input_run_count,
        "forward_eligible_run_count": forward_eligible_runs,
        "ignored_non_forward_run_count": ignored_non_forward_runs,
        "complete_run_count": complete_runs,
        "status_counts": dict(sorted(status_counts.items())),
        "coverage": {
            "expected_pair_count": expected_pairs,
            "observed_pair_count": observed_pairs,
            "observed_pair_rate": coverage_rate,
        },
        "failure_reason_counts": dict(sorted(reason_counts.items())),
        "affected_symbols_by_reason": {
            reason: sorted(symbols_by_reason[reason]) for reason in sorted(symbols_by_reason)
        },
    }


def summarize_files(paths: Iterable[Path]) -> dict[str, Any]:
    ordered = sorted({Path(path) for path in paths}, key=lambda path: str(path))
    if not ordered:
        raise ValueError("At least one prediction JSON file is required")
    return summarize_payloads(_load_payload(path) for path in ordered)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize score-blind long-horizon V5 collection health for genuine "
            "forward-eligible runs only."
        )
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    summary = summarize_files(args.inputs)
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
