from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from evals.intraday_challenger_tournament import compare_reports

LONG_HORIZONS = ("3h", "5h")
PREREGISTERED_CUTOFF_UTC = "2026-09-11T00:00:00+00:00"
EVIDENCE_MODES = ("historical_screen", "forward_holdout")

SEMANTICS = (
    "Pre-registered research gate for a future Orion regular-hours long-horizon challenger. "
    "The candidate is judged only on the 3h and 5h horizons fixed before new forward evidence "
    "arrives. Historical evidence may screen a design but can never make it research-eligible. "
    "Forward-holdout eligibility requires every paired challenger observation to occur at or "
    "after the pre-registration cutoff and both horizons to pass the existing paired proper-score "
    "and session-block-bootstrap tournament."
)


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _paired_forward_coverage(
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    horizons: Sequence[str] = LONG_HORIZONS,
    cutoff_utc: str = PREREGISTERED_CUTOFF_UTC,
) -> Dict[str, Any]:
    cutoff = _parse_timestamp(cutoff_utc)
    if cutoff is None:
        raise ValueError("cutoff_utc must be a valid ISO-8601 timestamp")

    incumbent_records = incumbent.get("prediction_records") or {}
    challenger_records = challenger.get("prediction_records") or {}
    if not isinstance(incumbent_records, Mapping) or not isinstance(challenger_records, Mapping):
        raise ValueError("Both reports must contain prediction_records mappings")

    details: Dict[str, Any] = {}
    all_forward = True
    for horizon in horizons:
        incumbent_by_ts = {
            str(row.get("timestamp")): row
            for row in (incumbent_records.get(horizon) or [])
            if isinstance(row, Mapping) and row.get("timestamp")
        }
        challenger_by_ts = {
            str(row.get("timestamp")): row
            for row in (challenger_records.get(horizon) or [])
            if isinstance(row, Mapping) and row.get("timestamp")
        }
        paired_timestamps = sorted(set(incumbent_by_ts) & set(challenger_by_ts))
        parsed = [_parse_timestamp(ts) for ts in paired_timestamps]
        invalid = sum(ts is None for ts in parsed)
        before_cutoff = sum(ts is not None and ts < cutoff for ts in parsed)
        horizon_forward = bool(paired_timestamps) and invalid == 0 and before_cutoff == 0
        all_forward = all_forward and horizon_forward
        details[horizon] = {
            "paired_timestamp_count": len(paired_timestamps),
            "invalid_timestamp_count": invalid,
            "before_cutoff_count": before_cutoff,
            "all_paired_observations_after_cutoff": horizon_forward,
        }

    return {
        "cutoff_utc": cutoff.isoformat(),
        "all_required_horizons_forward_only": all_forward,
        "horizons": details,
    }


def evaluate_long_horizon_candidate(
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    evidence_mode: str,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
    seed: int = 20260911,
) -> Dict[str, Any]:
    if evidence_mode not in EVIDENCE_MODES:
        raise ValueError(f"evidence_mode must be one of {EVIDENCE_MODES}")

    tournament = compare_reports(
        incumbent,
        challenger,
        horizons=LONG_HORIZONS,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    forward_coverage = _paired_forward_coverage(incumbent, challenger)

    tournament_passed = tournament.get("research_conclusion") == "challenger_research_eligible"
    if evidence_mode == "historical_screen":
        conclusion = "historical_screen_only"
        forward_eligible = False
    elif not forward_coverage["all_required_horizons_forward_only"]:
        conclusion = "forward_holdout_contaminated_or_missing"
        forward_eligible = False
    elif tournament_passed:
        conclusion = "long_horizon_challenger_research_eligible"
        forward_eligible = True
    else:
        conclusion = "long_horizon_challenger_not_demonstrated"
        forward_eligible = False

    return {
        "contract": "orion-long-horizon-challenger-gate-v1",
        "semantics": SEMANTICS,
        "research_only": True,
        "runtime_modified": False,
        "promotion_allowed": False,
        "pre_registered_horizons": list(LONG_HORIZONS),
        "pre_registered_cutoff_utc": PREREGISTERED_CUTOFF_UTC,
        "evidence_mode": evidence_mode,
        "forward_coverage": forward_coverage,
        "paired_tournament": tournament,
        "forward_research_eligible": forward_eligible,
        "research_conclusion": conclusion,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-registered 3h/5h Orion challenger research gate.")
    parser.add_argument("incumbent_report")
    parser.add_argument("challenger_report")
    parser.add_argument("--evidence-mode", choices=EVIDENCE_MODES, required=True)
    parser.add_argument("--output")
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-sessions", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args()

    incumbent = json.loads(Path(args.incumbent_report).read_text(encoding="utf-8"))
    challenger = json.loads(Path(args.challenger_report).read_text(encoding="utf-8"))
    result = evaluate_long_horizon_candidate(
        incumbent,
        challenger,
        evidence_mode=args.evidence_mode,
        min_observations=args.min_observations,
        min_sessions=args.min_sessions,
        bootstrap_samples=args.bootstrap_samples,
    )
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
