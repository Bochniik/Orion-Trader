from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evals" / "adaptive_research_error_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("adaptive_research_error_diagnostics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _record(day: int, index: int, *, p: float, actual: int, symbol: str = "AAPL", horizon: str = "1h"):
    return {
        "engine": "regular_hours_v3_1",
        "symbol": symbol,
        "horizon": horizon,
        "prediction_time_utc": f"2026-08-{day:02d}T14:{index:02d}:00+00:00",
        "target_time_utc": f"2026-08-{day:02d}T15:{index:02d}:00+00:00",
        "probability_up": p,
        "actual_up": actual,
        "record_id": f"{day}-{index}-{symbol}-{horizon}",
        "material_sha256": f"sha-{day}-{index}-{symbol}-{horizon}",
        "reliability_profile_source": "generic",
    }


def _ledger(records):
    return {"contract": MODULE.LEDGER_CONTRACT, "records": records}


def test_rejects_non_evidence_contract():
    with pytest.raises(ValueError, match="Unsupported evidence ledger contract"):
        MODULE.build_diagnostics({"contract": "wrong", "records": []})


def test_deduplicates_identical_record_id_and_fails_closed_on_conflict():
    row = _record(1, 1, p=0.7, actual=1)
    result = MODULE.build_diagnostics(_ledger([row, dict(row)]), min_observations=1, min_sessions=1)
    assert result["settled_observations"] == 1

    broken = dict(row)
    broken["probability_up"] = 0.2
    with pytest.raises(ValueError, match="Conflicting duplicate settled evidence"):
        MODULE.build_diagnostics(_ledger([row, broken]), min_observations=1, min_sessions=1)


def test_emits_only_covered_statistically_separated_failure_pattern():
    records = []
    for day in range(1, 7):
        for index in range(10):
            if index < 2:
                # High-confidence bucket: deliberately wrong across every session.
                records.append(_record(day, index, p=0.92, actual=0))
            else:
                # Remaining rows are mostly correct and define a much lower horizon baseline.
                actual = (day + index) % 2
                p = 0.65 if actual else 0.35
                records.append(_record(day, index, p=p, actual=actual))

    result = MODULE.build_diagnostics(
        _ledger(records),
        min_observations=10,
        min_sessions=4,
        min_excess_error=0.10,
    )
    patterns = result["candidate_failure_patterns"]
    high_conf = [
        row for row in patterns
        if row["dimension"] == "confidence_band" and row["value"] == "90-100"
    ]
    assert len(high_conf) == 1
    assert high_conf[0]["error_rate"] == 1.0
    assert high_conf[0]["baseline_error_rate"] == 0.2
    assert high_conf[0]["error_rate_ci95"][0] > high_conf[0]["baseline_error_rate"]


def test_small_or_single_session_slices_do_not_become_hypotheses():
    records = [
        _record(1, index, p=0.95, actual=0, symbol="TSLA")
        for index in range(10)
    ]
    records.extend(
        _record(day, 20 + day, p=0.55, actual=1, symbol="AAPL")
        for day in range(1, 7)
    )
    result = MODULE.build_diagnostics(
        _ledger(records),
        min_observations=8,
        min_sessions=3,
        min_excess_error=0.05,
    )
    assert not any(
        row["dimension"] == "symbol" and row["value"] == "TSLA"
        for row in result["candidate_failure_patterns"]
    )


def test_report_forbids_same_evidence_promotion_and_runtime_change():
    records = [_record(day, day, p=0.6, actual=1) for day in range(1, 5)]
    result = MODULE.build_diagnostics(
        _ledger(records),
        min_observations=1,
        min_sessions=1,
    )
    assert result["contract"] == MODULE.CONTRACT
    assert result["safety"]["research_only"] is True
    assert result["safety"]["runtime_modified"] is False
    assert result["safety"]["automatic_promotion_allowed"] is False
    assert result["safety"]["same_evidence_promotion_forbidden"] is True
    assert result["safety"]["candidate_requires_new_identity"] is True
    assert result["safety"]["candidate_requires_later_preregistered_forward_cutoff"] is True
