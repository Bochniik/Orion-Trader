from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from app.services import intraday_probability_ensemble_engine  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


settler = _load("long_horizon_v5_score_blind_settler", "scripts/settle_long_horizon_v5_shadow.py")


def _record(*, engine: str, actual_up: int, probability_up: float, session: str = "2026-09-11"):
    return settler.ForecastRecord(
        source_file="prediction.json",
        engine=engine,
        symbol="AAPL",
        horizon="5h",
        horizon_minutes=300,
        prediction_time_utc=f"{session}T14:05:00+00:00",
        target_time_utc=f"{session}T19:05:00+00:00",
        probability_up=probability_up,
        predicted_direction="bullish" if probability_up >= 0.5 else "bearish",
        actual_up=actual_up,
        base_price=100.0,
        outcome_price=105.0 if actual_up else 95.0,
        realized_return_pct=5.0 if actual_up else -5.0,
        correct_direction=(probability_up >= 0.5) == bool(actual_up),
        brier=(probability_up - actual_up) ** 2,
        log_loss=0.1,
        lineage={"paired_role": "challenger" if "v5" in engine else "incumbent"},
    )


def test_score_blind_settlement_summary_is_outcome_invariant():
    favorable = [_record(engine="long-horizon-v5-20260911-a", actual_up=1, probability_up=0.95)]
    unfavorable = [_record(engine="long-horizon-v5-20260911-a", actual_up=0, probability_up=0.95)]

    assert settler._score_blind_summary(favorable, 2) == settler._score_blind_summary(unfavorable, 2)
    assert settler._score_blind_summary(favorable, 2) == {
        "forecasts_considered": 2,
        "settled_observations": 1,
        "distinct_sessions": 1,
        "score_blind": True,
        "metrics_exposed": False,
    }


def test_score_blind_grouped_summary_contains_coverage_only():
    rows = [
        _record(engine="regular_hours_v3_1", actual_up=1, probability_up=0.55),
        _record(engine="long-horizon-v5-20260911-a", actual_up=1, probability_up=0.95),
    ]
    grouped = settler._score_blind_grouped_summaries(rows)

    assert set(grouped) == {"regular_hours_v3_1:5h", "long-horizon-v5-20260911-a:5h"}
    serialized = str(grouped).lower()
    for forbidden in ("brier", "log_loss", "accuracy", "probability", "actual_up", "correct_direction"):
        assert forbidden not in serialized
    assert all(summary["metrics_exposed"] is False for summary in grouped.values())


def test_long_horizon_evidence_workflow_enables_score_blind_settlement():
    workflow = (ROOT / ".github/workflows/long-horizon-v5-evidence-cycle.yml").read_text(encoding="utf-8")
    command_block = workflow.split("python scripts/settle_long_horizon_v5_shadow.py", 1)[1].split("- name: Accumulate", 1)[0]
    assert "--score-blind-summary" in command_block
