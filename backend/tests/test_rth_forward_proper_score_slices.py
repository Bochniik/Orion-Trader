from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1] / "evals"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))
MODULE_PATH = EVAL_DIR / "rth_forward_proper_score_slices.py"
SPEC = importlib.util.spec_from_file_location("rth_forward_proper_score_slices", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _record(day: int, symbol: str, *, p: float, actual: int, horizon: str = "30m"):
    return {
        "engine": "regular_hours_v3_1",
        "symbol": symbol,
        "horizon": horizon,
        "prediction_time_utc": f"2026-09-{day:02d}T14:00:00+00:00",
        "target_time_utc": f"2026-09-{day:02d}T15:00:00+00:00",
        "probability_up": p,
        "actual_up": actual,
        "record_id": f"{day}-{symbol}-{horizon}",
        "material_sha256": f"sha-{day}-{symbol}-{horizon}",
    }


def _ledger(records):
    return {"contract": MODULE.baseline.LEDGER_CONTRACT, "records": records}


def test_report_localizes_proper_score_deficits_and_stays_fail_closed():
    rows = [
        _record(1, "AAPL", p=0.55, actual=1),
        _record(1, "MSFT", p=0.45, actual=1),
        _record(2, "AAPL", p=0.80, actual=0),
        _record(2, "MSFT", p=0.20, actual=0),
    ]
    report = MODULE.build_report(_ledger(rows))
    horizon = report["horizons"]["30m"]
    assert set(horizon["by_direction"]) == {"DOWN", "UP"}
    assert set(horizon["by_confidence_band"]) == {"50-60", "80-90"}
    assert horizon["overall"]["observations"] == 4
    assert report["promotion_gate"]["eligible"] is False
    assert report["safety"]["runtime_modified"] is False


def test_slices_reuse_full_horizon_prior_instead_of_recomputing_subset_history():
    rows = [
        _record(1, "AAPL", p=0.55, actual=1),
        _record(1, "MSFT", p=0.45, actual=1),
        _record(2, "AAPL", p=0.55, actual=0),
        _record(2, "MSFT", p=0.45, actual=0),
    ]
    report = MODULE.build_report(_ledger(rows))
    # Day-1 outcomes are both UP, so every day-2 row must inherit prior=1.0.
    # If the DOWN slice incorrectly recomputed its own history, it would use only MSFT's day-1 outcome;
    # this fixture deliberately checks the report remains tied to the full horizon-local causal stream.
    down = report["horizons"]["30m"]["by_direction"]["DOWN"]
    assert down["chronological_expanding_prior"]["brier_score"] == 0.5


def test_horizon_priors_remain_isolated_inside_slices():
    rows = [
        _record(1, "AAPL", p=0.6, actual=1, horizon="30m"),
        _record(2, "AAPL", p=0.6, actual=0, horizon="1h"),
        _record(3, "AAPL", p=0.6, actual=0, horizon="30m"),
        _record(3, "MSFT", p=0.6, actual=1, horizon="1h"),
    ]
    report = MODULE.build_report(_ledger(rows))
    assert set(report["horizons"]) == {"30m", "1h"}
    assert report["horizons"]["30m"]["overall"]["chronological_expanding_prior"]["brier_score"] == 0.625
    assert report["horizons"]["1h"]["overall"]["chronological_expanding_prior"]["brier_score"] == 0.625
