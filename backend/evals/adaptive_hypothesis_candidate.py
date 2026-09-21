from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.evals.adaptive_challenger_registry import register_candidate

DIAGNOSTICS_CONTRACT = "orion-adaptive-research-diagnostics-v1"
CONTRACT = "orion-adaptive-hypothesis-candidate-v1"
ALLOWED_DIMENSIONS = {
    "direction",
    "confidence_band",
    "symbol",
    "reliability_profile_source",
}


def _parse_utc(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _diagnostics_cutoff(payload: Mapping[str, Any]) -> datetime:
    if payload.get("contract") != DIAGNOSTICS_CONTRACT:
        raise ValueError(f"Unsupported diagnostics contract: {payload.get('contract')}")
    created = _parse_utc(payload.get("created_at_utc"), field="created_at_utc")
    if payload.get("safety", {}).get("same_evidence_promotion_forbidden") is not True:
        raise ValueError("diagnostics must forbid same-evidence promotion")
    return created


def build_candidate_spec(
    diagnostics: Mapping[str, Any],
    *,
    pattern_index: int,
    change_summary: str,
    code_sha: str,
    forward_cutoff_utc: str,
    evaluation_contract: str,
) -> dict[str, Any]:
    development_cutoff = _diagnostics_cutoff(diagnostics)
    patterns = diagnostics.get("candidate_failure_patterns")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError("diagnostics contain no eligible candidate failure patterns")
    if pattern_index < 0 or pattern_index >= len(patterns):
        raise ValueError("pattern_index is out of range")
    pattern = patterns[pattern_index]
    if not isinstance(pattern, Mapping) or pattern.get("status") != "candidate_failure_pattern":
        raise ValueError("selected pattern is not an eligible candidate failure pattern")

    dimension = str(pattern.get("dimension") or "")
    horizon = str(pattern.get("horizon") or "")
    value = str(pattern.get("value") or "")
    if dimension not in ALLOWED_DIMENSIONS or not horizon or not value:
        raise ValueError("selected failure pattern is incomplete or unsupported")

    forward_cutoff = _parse_utc(forward_cutoff_utc, field="forward_cutoff_utc")
    if forward_cutoff <= development_cutoff:
        raise ValueError("forward cutoff must be later than diagnostics/development evidence")
    if not change_summary.strip() or not code_sha.strip() or not evaluation_contract.strip():
        raise ValueError("change_summary, code_sha, and evaluation_contract are required")

    hypothesis = (
        f"Reduce the preregistered {horizon} settled-error pattern for "
        f"{dimension}={value} without degrading proper-score performance on untouched forward evidence."
    )
    return {
        "engine_family": str(diagnostics.get("engine") or "regular_hours"),
        "hypothesis": hypothesis,
        "change_summary": change_summary.strip(),
        "development_evidence_cutoff_utc": development_cutoff.isoformat(),
        "forward_cutoff_utc": forward_cutoff.isoformat(),
        "code_sha": code_sha.strip(),
        "horizons": [horizon],
        "evaluation_protocol": {
            "contract": evaluation_contract.strip(),
            "selected_failure_pattern": {
                "dimension": dimension,
                "value": value,
                "horizon": horizon,
                "observations": int(pattern.get("observations") or 0),
                "distinct_sessions": int(pattern.get("distinct_sessions") or 0),
                "baseline_error_rate": pattern.get("baseline_error_rate"),
                "error_rate": pattern.get("error_rate"),
                "excess_error_rate": pattern.get("excess_error_rate"),
            },
            "selection_rule": "single_preregistered_diagnostic_pattern",
            "same_evidence_approval_forbidden": True,
        },
    }


def build_registration(
    diagnostics: Mapping[str, Any],
    *,
    pattern_index: int,
    change_summary: str,
    code_sha: str,
    forward_cutoff_utc: str,
    evaluation_contract: str,
    registered_at_utc: str | None = None,
) -> dict[str, Any]:
    spec = build_candidate_spec(
        diagnostics,
        pattern_index=pattern_index,
        change_summary=change_summary,
        code_sha=code_sha,
        forward_cutoff_utc=forward_cutoff_utc,
        evaluation_contract=evaluation_contract,
    )
    registration = register_candidate(spec, registered_at_utc=registered_at_utc)
    return {
        "contract": CONTRACT,
        "selected_pattern_index": pattern_index,
        "registration": registration,
        "safety": {
            "research_only": True,
            "runtime_modified": False,
            "automatic_promotion_allowed": False,
            "same_evidence_approval_forbidden": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one bounded preregistered Orion challenger from settled diagnostics.")
    parser.add_argument("diagnostics", type=Path)
    parser.add_argument("--pattern-index", type=int, default=0)
    parser.add_argument("--change-summary", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--forward-cutoff", required=True)
    parser.add_argument("--evaluation-contract", required=True)
    parser.add_argument("--registered-at")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    diagnostics = json.loads(args.diagnostics.read_text(encoding="utf-8"))
    result = build_registration(
        diagnostics,
        pattern_index=args.pattern_index,
        change_summary=args.change_summary,
        code_sha=args.code_sha,
        forward_cutoff_utc=args.forward_cutoff,
        evaluation_contract=args.evaluation_contract,
        registered_at_utc=args.registered_at,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
