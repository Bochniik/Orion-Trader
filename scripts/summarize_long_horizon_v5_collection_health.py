from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any, Iterable

CONTRACT = "orion-long-horizon-v5-paired-shadow-v1"
SUMMARY_CONTRACT = "orion-long-horizon-v5-collection-health-v1"


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


def summarize_payloads(payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    symbols_by_reason: dict[str, set[str]] = defaultdict(set)
    run_count = 0
    forward_eligible_runs = 0
    complete_runs = 0
    expected_pairs = 0
    observed_pairs = 0

    for payload in payloads:
        run_count += 1
        status_counts[str(payload.get("status") or "unknown")] += 1

        provenance = payload.get("acquisition_provenance") or {}
        if isinstance(provenance, dict) and provenance.get("forward_eligible") is True:
            forward_eligible_runs += 1

        coverage = payload.get("coverage") or {}
        if isinstance(coverage, dict):
            expected_pairs += int(coverage.get("expected_pair_count") or 0)
            observed_pairs += int(coverage.get("observed_pair_count") or 0)
            if coverage.get("complete") is True:
                complete_runs += 1

        failures = payload.get("failures") or {}
        if not isinstance(failures, dict):
            raise ValueError("failures must be a JSON object")
        for symbol, reason in failures.items():
            category = _reason_category(reason)
            reason_counts[category] += 1
            symbols_by_reason[category].add(str(symbol).upper())

    coverage_rate = None
    if expected_pairs > 0:
        coverage_rate = round(observed_pairs / expected_pairs, 6)

    return {
        "contract": SUMMARY_CONTRACT,
        "score_blind": True,
        "run_count": run_count,
        "forward_eligible_run_count": forward_eligible_runs,
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
        description="Summarize score-blind long-horizon V5 collection health without reading model scores."
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
