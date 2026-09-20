from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .adaptive_challenger_registry import assert_forward_evidence_eligible, validate_registration
    from .intraday_challenger_tournament import HORIZONS, compare_reports
except ImportError:  # direct script execution
    from adaptive_challenger_registry import assert_forward_evidence_eligible, validate_registration
    from intraday_challenger_tournament import HORIZONS, compare_reports

CONTRACT = "orion-registered-challenger-tournament-v1"


def _challenger_evidence(report: Mapping[str, Any], horizons: Sequence[str]) -> list[dict[str, Any]]:
    records = report.get("prediction_records")
    if not isinstance(records, Mapping):
        raise ValueError("challenger report must contain prediction_records mapping")
    flattened: list[dict[str, Any]] = []
    for horizon in horizons:
        rows = records.get(horizon) or []
        if not isinstance(rows, list):
            raise ValueError(f"challenger prediction_records.{horizon} must be a list")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError(f"challenger {horizon} evidence row must be an object")
            normalized = dict(row)
            normalized.setdefault("horizon", horizon)
            flattened.append(normalized)
    return flattened


def compare_registered_reports(
    registration: Mapping[str, Any],
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    horizons: Sequence[str] | None = None,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
    seed: int = 20260910,
) -> dict[str, Any]:
    validated = validate_registration(registration)
    registered_horizons = tuple(validated["candidate"]["horizons"])
    requested = tuple(horizons) if horizons is not None else registered_horizons
    if not requested:
        raise ValueError("registered challenger must declare at least one horizon")
    if set(requested) != set(registered_horizons):
        raise ValueError("tournament horizons must exactly match the immutable registration")

    evidence = _challenger_evidence(challenger, requested)
    eligibility = assert_forward_evidence_eligible(validated, evidence)
    if not eligibility["forward_evidence_eligible"]:
        raise ValueError(
            "challenger evidence violates immutable forward boundary: "
            f"invalid_timestamp_count={eligibility['invalid_timestamp_count']}, "
            f"at_or_before_cutoff_count={eligibility['at_or_before_cutoff_count']}, "
            f"wrong_horizon_count={eligibility['wrong_horizon_count']}, "
            f"observations={eligibility['observations']}"
        )

    tournament = compare_reports(
        incumbent,
        challenger,
        horizons=requested,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    return {
        "contract": CONTRACT,
        "candidate_id": validated["candidate_id"],
        "immutable_material_sha256": validated["immutable_material_sha256"],
        "forward_evidence": eligibility,
        "registration_required": True,
        "runtime_modified": False,
        "automatic_promotion_allowed": False,
        "tournament": tournament,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Leakage-safe Orion challenger tournament requiring immutable preregistration."
    )
    parser.add_argument("registration", type=Path)
    parser.add_argument("incumbent_report", type=Path)
    parser.add_argument("challenger_report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-sessions", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args()

    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    incumbent = json.loads(args.incumbent_report.read_text(encoding="utf-8"))
    challenger = json.loads(args.challenger_report.read_text(encoding="utf-8"))
    result = compare_registered_reports(
        registration,
        incumbent,
        challenger,
        min_observations=args.min_observations,
        min_sessions=args.min_sessions,
        bootstrap_samples=args.bootstrap_samples,
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
