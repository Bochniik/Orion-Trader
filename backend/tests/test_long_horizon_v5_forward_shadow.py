from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _load("long_horizon_shadow_runner", "scripts/run_long_horizon_v5_paired_cloud_shadow.py")
settler = _load("long_horizon_shadow_settler", "scripts/settle_long_horizon_v5_shadow.py")


def test_session_gate_is_score_blind_and_bounded_to_settleable_window():
    allowed = runner.session_gate(datetime(2026, 9, 11, 15, 5, tzinfo=timezone.utc))
    assert allowed["allowed"] is True
    assert allowed["window_et"] == "10:00-13:30"

    late = runner.session_gate(datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc))
    assert late["allowed"] is False


def test_atomic_runner_pairs_incumbent_and_challenger_on_exact_timestamp(monkeypatch):
    monkeypatch.setattr(
        runner,
        "estimate_long_horizon_v5",
        lambda symbol: {
            "available": True,
            "as_of": "2026-09-11T14:05:00+00:00",
            "horizons": {
                "3h": {"available": True, "probability_up": 0.61, "direction": "bullish", "target_time_utc": "2026-09-11T17:05:00+00:00", "training_samples": 900, "training_cutoff": "2026-09-11T11:05:00+00:00", "max_training_timestamp": "2026-09-11T11:05:00+00:00"},
                "5h": {"available": True, "probability_up": 0.57, "direction": "bullish", "target_time_utc": "2026-09-11T19:05:00+00:00", "training_samples": 800, "training_cutoff": "2026-09-11T09:05:00+00:00", "max_training_timestamp": "2026-09-11T09:05:00+00:00"},
            },
        },
    )
    monkeypatch.setattr(
        runner,
        "estimate_intraday_probabilities_v3_1",
        lambda symbol: {
            "horizons": {
                "3h": {"probability_up": 58.0, "direction": "bullish", "suppressed": False},
                "5h": {"probability_up": None, "suppressed_probability_up": 54.0, "direction": "neutral", "suppressed": True},
            }
        },
    )
    rows, error = runner.run_symbol("AAPL")
    assert error is None
    assert len(rows) == 2
    assert {row["horizon"] for row in rows} == {"3h", "5h"}
    assert {row["prediction_time_utc"] for row in rows} == {"2026-09-11T14:05:00+00:00"}
    five_hour = next(row for row in rows if row["horizon"] == "5h")
    assert five_hour["incumbent"]["probability_up"] == 0.54
    assert five_hour["incumbent"]["was_runtime_suppressed"] is True


def test_settlement_expansion_preserves_pair_identity_and_model_names():
    payload = {
        "contract": settler.CONTRACT,
        "lineage": {"git_commit": "abc", "design_id": "long-horizon-v5-20260911-a"},
        "paired_predictions": [{
            "symbol": "AAPL",
            "horizon": "3h",
            "prediction_time_utc": "2026-09-11T14:05:00+00:00",
            "incumbent": {"engine": "regular_hours_v3_1", "probability_up": 0.55, "direction": "bullish"},
            "challenger": {"engine": "long-horizon-v5-20260911-a", "probability_up": 0.60, "direction": "bullish"},
        }],
    }
    forecasts = settler.expand_payload(payload, "prediction.json")
    assert len(forecasts) == 2
    assert {row["engine"] for row in forecasts} == {"regular_hours_v3_1", "long-horizon-v5-20260911-a"}
    assert {row["prediction_time"] for row in forecasts} == {"2026-09-11T14:05:00+00:00"}
    assert {row["lineage"]["paired_role"] for row in forecasts} == {"incumbent", "challenger"}


def test_workflows_are_research_only_and_do_not_expose_write_permissions():
    for relative in (
        ".github/workflows/long-horizon-v5-cloud-shadow.yml",
        ".github/workflows/long-horizon-v5-evidence-cycle.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "contents: write" not in text
        assert "orders" not in text.lower()
        assert "actions: write" not in text
    prediction = (ROOT / ".github/workflows/long-horizon-v5-cloud-shadow.yml").read_text(encoding="utf-8")
    assert "retention-days: 45" in prediction
    assert "run_long_horizon_v5_paired_cloud_shadow.py" in prediction
