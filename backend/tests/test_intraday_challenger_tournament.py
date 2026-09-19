from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evals" / "intraday_challenger_tournament.py"
SPEC = importlib.util.spec_from_file_location("intraday_challenger_tournament", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _records(*, challenger: bool, sessions: int = 10, rows_per_session: int = 10):
    records = []
    for day in range(1, sessions + 1):
        for index in range(rows_per_session):
            actual = (day + index) % 2
            p = (78.0 if actual else 22.0) if challenger else (58.0 if actual else 42.0)
            records.append({"timestamp": f"2026-08-{day:02d}T{14 + index // 6:02d}:{(index % 6) * 5:02d}:00+00:00", "p_up": p, "actual_up": actual})
    return records


def _registration(*, cutoff="2026-07-31T23:59:59+00:00", horizons=None):
    return MODULE.validate_registration(MODULE.register_candidate({
        "engine_family": "regular_hours",
        "hypothesis": "synthetic test challenger improves proper scores",
        "change_summary": "test-only probability separation",
        "development_evidence_cutoff_utc": "2026-07-01T00:00:00+00:00",
        "forward_cutoff_utc": cutoff,
        "code_sha": "test-sha",
        "horizons": list(horizons or MODULE.HORIZONS),
        "evaluation_protocol": {"contract": "orion-intraday-challenger-tournament-v2"},
    }, registered_at_utc="2026-07-15T00:00:00+00:00"))


def test_pair_records_aligns_exact_timestamps_and_rejects_outcome_mismatch():
    incumbent = _records(challenger=False, sessions=2, rows_per_session=3); challenger = _records(challenger=True, sessions=2, rows_per_session=3)
    challenger.append({"timestamp": "2026-08-20T14:00:00+00:00", "p_up": 90, "actual_up": 1})
    assert len(MODULE.pair_records(incumbent, challenger)) == 6
    broken = copy.deepcopy(challenger); broken[0]["actual_up"] = 1 - broken[0]["actual_up"]
    with pytest.raises(ValueError, match="Outcome mismatch"): MODULE.pair_records(incumbent, broken)


def test_conflicting_duplicate_fails_closed():
    rows = _records(challenger=False, sessions=1, rows_per_session=2); duplicate = dict(rows[0]); duplicate["p_up"] = 99.0
    with pytest.raises(ValueError, match="Conflicting duplicate"): MODULE.pair_records(rows + [duplicate], rows)


def test_strong_challenger_is_research_eligible_with_session_block_bootstrap():
    result = MODULE.evaluate_paired_horizon(_records(challenger=False), _records(challenger=True), min_observations=80, min_sessions=8, bootstrap_samples=300, seed=7)
    assert result["coverage_ok"] is True; assert result["brier_improvement"] > 0; assert result["log_loss_improvement"] > 0; assert result["bootstrap"]["brier_improvement_ci95"][0] > 0; assert result["bootstrap"]["log_loss_improvement_ci95"][0] > 0; assert result["verdict"] == "research_eligible"


def test_high_confidence_bad_tail_cannot_pass_on_directional_story_alone():
    incumbent=[]; challenger=[]
    for day in range(1,11):
        for index in range(10):
            actual=(day+index)%2; timestamp=f"2026-08-{day:02d}T14:{index*5:02d}:00+00:00"; incumbent.append({"timestamp":timestamp,"actual_up":actual,"p_up":51 if actual else 49}); challenger.append({"timestamp":timestamp,"actual_up":actual,"p_up":(99 if actual else 1) if index<8 else (1 if actual else 99)})
    result=MODULE.evaluate_paired_horizon(incumbent,challenger,min_observations=80,min_sessions=8,bootstrap_samples=200,seed=9)
    assert result["challenger"]["directional_accuracy"] > .5; assert result["verdict"] == "not_demonstrated"


def test_insufficient_sessions_fails_closed_even_when_scores_improve():
    result=MODULE.evaluate_paired_horizon(_records(challenger=False,sessions=3,rows_per_session=30),_records(challenger=True,sessions=3,rows_per_session=30),min_observations=80,min_sessions=8,bootstrap_samples=100)
    assert result["paired_observations"]==90; assert result["distinct_sessions"]==3; assert result["coverage_ok"] is False; assert result["verdict"]=="not_demonstrated"


def test_compare_reports_requires_valid_preregistration_and_every_horizon_to_pass():
    incumbent_records=_records(challenger=False); challenger_records=_records(challenger=True); incumbent={"prediction_records":{h:incumbent_records for h in MODULE.HORIZONS}}; challenger={"prediction_records":{h:challenger_records for h in MODULE.HORIZONS}}
    result=MODULE.compare_reports(incumbent,challenger,registration=_registration(),min_observations=80,min_sessions=8,bootstrap_samples=150)
    assert result["research_conclusion"]=="challenger_research_eligible"; assert result["eligible_horizons"]==4; assert result["preregistration_required"] is True; assert result["registration_gate"]["observations_checked"]==400
    challenger["prediction_records"]["5h"]=challenger_records[:20]
    result=MODULE.compare_reports(incumbent,challenger,registration=_registration(),min_observations=80,min_sessions=8,bootstrap_samples=150)
    assert result["research_conclusion"]=="challenger_not_demonstrated"; assert result["eligible_horizons"]==3


def test_tournament_rejects_pre_cutoff_evidence_even_if_scores_are_strong():
    rows=_records(challenger=True); incumbent={"prediction_records":{h:_records(challenger=False) for h in MODULE.HORIZONS}}; challenger={"prediction_records":{h:rows for h in MODULE.HORIZONS}}
    with pytest.raises(ValueError, match="violates immutable preregistration"):
        MODULE.compare_reports(incumbent,challenger,registration=_registration(cutoff="2026-08-05T23:59:59+00:00"),bootstrap_samples=20)


def test_tournament_rejects_registration_missing_required_horizon():
    incumbent={"prediction_records":{h:_records(challenger=False) for h in MODULE.HORIZONS}}; challenger={"prediction_records":{h:_records(challenger=True) for h in MODULE.HORIZONS}}
    with pytest.raises(ValueError, match="does not cover tournament horizons"):
        MODULE.compare_reports(incumbent,challenger,registration=_registration(horizons=["30m","1h","3h"]),bootstrap_samples=20)
