from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.evals.adaptive_forward_evidence import assess_forward_evidence_readiness
from backend.evals.intraday_challenger_tournament import (
    BOOTSTRAP_SAMPLES,
    DEFAULT_SEED,
    HORIZONS,
    compare_reports,
)

CONTRACT = "orion-adaptive-tournament-entry-v1"


def compare_registered_challenger(
    registration: Mapping[str, Any],
    forward_evidence: list[Mapping[str, Any]],
    incumbent_report: Mapping[str, Any],
    challenger_report: Mapping[str, Any],
    *,
    horizons: Sequence[str] | None = None,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Score an adaptive challenger only after its immutable forward cohort is ready.

    The generic tournament remains available for frozen/manual research. Adaptive
    challengers must enter through this fail-closed wrapper so readiness cannot be
    bypassed by caller-supplied sample thresholds.
    """
    readiness = assess_forward_evidence_readiness(registration, forward_evidence)
    if not readiness["tournament_ready"]:
        raise ValueError("adaptive challenger forward evidence is not tournament-ready")

    registered_horizons = tuple(registration["candidate"]["horizons"])
    requested_horizons = tuple(horizons) if horizons is not None else registered_horizons
    if requested_horizons != registered_horizons:
        raise ValueError("adaptive tournament horizons must exactly match preregistered horizons")

    protocol = registration["candidate"]["evaluation_protocol"]
    min_observations = int(protocol["min_forward_observations"])
    min_sessions = int(protocol["min_forward_distinct_sessions"])

    result = compare_reports(
        incumbent_report,
        challenger_report,
        horizons=requested_horizons,
        min_observations=min_observations,
        min_sessions=min_sessions,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    return {
        "contract": CONTRACT,
        "candidate_id": readiness["candidate_id"],
        "readiness": readiness,
        "tournament": result,
        "safety": {
            "research_only": True,
            "runtime_modified": False,
            "automatic_promotion_allowed": False,
            "readiness_required_before_scoring": True,
            "thresholds_from_preregistered_contract": True,
        },
    }
