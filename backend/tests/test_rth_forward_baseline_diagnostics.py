from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evals" / "rth_forward_baseline_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("rth_forward_baseline_diagnostics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _record(day: int, minute: int, symbol: str, *, p: float, actual: int, horizon: str = "30m"):
    return {
        "engine": "regular_hours_v3_1",
        "symbol": symbol,
        "horizon": horizon,
        "prediction_time_utc": f"2026-09-{day:02d}T14:{minute:02d}:00+00:00",
        "target_time_utc": f"2026-09-{day:02d}T15:{minute:02d}:00+00:00",
        "probability_up": p,
        "actual_up": actual,
        "record_id": f"{day}-{minute}-{symbol}-{horizon}",
        "material_sha256": f"sha-{day}-{minute}-{symbol}-{horizon}",
    }


def _ledger(records):
    return {"contract": MODULE.LEDGER_CONTRACT, "records": records}


def test_rejects_wrong_contract_and_conflicting_duplicates():
    with pytest.raises(ValueError, match="Unsupported evidence ledger contract"):
        MODULE.build_report({"contract": "wrong", "records": []})
    row = _record(1, 0, "AAPL", p=0.6, actual=1)
    broken = dict(row)
    broken["actual_up"] = 0
    with pytest.raises(ValueError, match="Conflicting duplicate settled evidence"):
        MODULE.build_report(_ledger([row, broken]))


def test_same_timestamp_outcomes_never_enter_each_others_prior():
    rows = [
        _record(1, 0, "AAPL", p=0.5, actual=1),
        _record(1, 0, "MSFT", p=0.5, actual=1),
        _record(2, 0, "AAPL", p=0.5, actual=0),
        _record(2, 0, "MSFT", p=0.5, actual=0),
    ]
    normalized = MODULE._normalize(_ledger(rows), "regular_hours_v3_1")
    ordered = sorted(normalized, key=lambda row: (row["prediction_time_utc"], row["symbol"]))
    assert MODULE._chronological_prior(ordered) == [0.5, 0.5, 1.0, 1.0]


def test_chronological_prior_never_cross_contaminates_horizons():
    rows = [
        _record(1, 0, "AAPL", p=0.5, actual=1, horizon="30m"),
        _record(1, 0, "MSFT", p=0.5, actual=1, horizon="30m"),
        _record(2, 0, "AAPL", p=0.5, actual=0, horizon="1h"),
        _record(2, 0, "MSFT", p=0.5, actual=0, horizon="1h"),
        _record(3, 0, "AAPL", p=0.5, actual=0, horizon="30m"),
        _record(3, 0, "MSFT", p=0.5, actual=0, horizon="1h"),
    ]
    normalized = MODULE._normalize(_ledger(rows), "regular_hours_v3_1")
    ordered = sorted(normalized, key=lambda row: (row["prediction_time_utc"], row["horizon"], row["symbol"]))
    priors = MODULE._chronological_prior(ordered)
    keyed = {(row["horizon"], row["prediction_time_utc"]): prior for row, prior in zip(ordered, priors)}
    assert keyed[("1h", "2026-09-02T14:00:00+00:00")] == 0.5
    assert keyed[("30m", "2026-09-03T14:00:00+00:00")] == 1.0
    assert keyed[("1h", "2026-09-03T14:00:00+00:00")] == 0.0


def test_report_exposes_proper_score_deltas_and_fail_closed_promotion():
    rows = [
        _record(1, 0, "AAPL", p=0.9, actual=1),
        _record(1, 0, "MSFT", p=0.9, actual=1),
        _record(2, 0, "AAPL", p=0.9, actual=0),
        _record(2, 0, "MSFT", p=0.9, actual=0),
    ]
    report = MODULE.build_report(_ledger(rows))
    comparison = report["horizons"]["30m"]
    assert comparison["model"]["observations"] == 4
    assert comparison["chronological_expanding_prior"]["brier_score"] == 0.625
    assert comparison["neutral_50_50"]["brier_score"] == 0.25
    assert comparison["model_minus_neutral"]["brier_score"] > 0
    assert comparison["beats_neutral_on_both_proper_scores"] is False
    assert report["promotion_gate"]["eligible"] is False
    assert report["safety"]["runtime_modified"] is False


def test_horizons_are_scored_independently():
    rows = [
        _record(1, 0, "AAPL", p=0.7, actual=1, horizon="30m"),
        _record(1, 0, "AAPL", p=0.3, actual=0, horizon="1h"),
    ]
    report = MODULE.build_report(_ledger(rows))
    assert set(report["horizons"]) == {"30m", "1h"}
    assert report["horizons"]["30m"]["model"]["brier_score"] == 0.09
    assert report["horizons"]["1h"]["model"]["brier_score"] == 0.09