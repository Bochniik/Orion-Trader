from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "simulate_premarket_market.py"
    spec = importlib.util.spec_from_file_location("premarket_synthetic_simulator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolves postponed annotations through sys.modules. Register
    # the dynamically loaded module before executing it, matching normal import
    # semantics instead of relying on an incomplete test-only import path.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scenario_generation_is_deterministic_and_covers_full_session():
    module = load_module()
    scenario = module.Scenario("deterministic", 2.0, 0.01, 0.05)
    frame_a, latent_a = module.generate_scenario(scenario, seed=123)
    frame_b, latent_b = module.generate_scenario(scenario, seed=123)

    assert len(latent_a) == 330
    assert len(frame_a) == 330
    assert frame_a.equals(frame_b)
    assert latent_a.equals(latent_b)
    assert latent_a.index[0].tz is not None
    assert latent_a.index[0].tz_convert("America/New_York").strftime("%H:%M") == "04:00"
    assert latent_a.index[-1].tz_convert("America/New_York").strftime("%H:%M") == "09:29"


def test_sparse_scenario_emits_missing_bars_but_keeps_latent_truth():
    module = load_module()
    scenario = module.Scenario("sparse", 1.0, 0.0, 0.1, bar_probability=0.25)
    frame, latent = module.generate_scenario(scenario, seed=99)

    assert len(latent) == 330
    assert 3 <= len(frame) < 250
    assert frame.index[0] == latent.index[0]
    assert frame.index[-1] == latent.index[-1]


def test_real_v5_and_live_synthesis_run_on_synthetic_session():
    module = load_module()
    result = module.run_scenario(
        module.Scenario("trend_up", 3.0, 0.02, 0.04, volume_scale=1.2),
        seed=7,
        evaluation_step_minutes=15,
    )

    assert result["snapshot_count"] > 5
    assert result["settlement_count"] > 10
    assert set(result["by_horizon"]) == {"5", "15", "30"}
    assert all(row["v5_available"] is True for row in result["snapshots"])
    assert all(0.0 <= row["premarket_orion_score"] <= 100.0 for row in result["snapshots"])
    assert 0.0 <= result["signal_rate"] <= 1.0
    assert 0.0 <= result["no_trade_rate"] <= 1.0


def test_lab_is_research_only_and_never_enables_orders():
    module = load_module()
    payload = module.run_lab(
        seed=3,
        scenarios=(
            module.Scenario("trend_up", 2.0, 0.02, 0.05),
            module.Scenario("chop", 0.0, 0.0, 0.12),
        ),
    )

    assert payload["contract"] == "orion-premarket-synthetic-lab-v1"
    assert payload["scenario_count"] == 2
    assert payload["research_only"] is True
    assert payload["order_submission_enabled"] is False
    assert len(payload["scenarios"]) == 2


def test_sparse_settlement_uses_observed_close_not_hidden_latent_price():
    module = load_module()
    frame, latent = module.generate_scenario(
        module.Scenario("sparse", 1.0, 0.01, 0.10, bar_probability=0.20),
        seed=99,
    )
    # Select a decision minute with no bar to reproduce stale observed data.
    as_of = next(t for t in latent.index[60:-30] if t not in frame.index)
    visible = frame.loc[frame.index <= as_of]
    observed_at = visible.index[-1]
    observed_price = float(visible["Close"].iloc[-1])
    assert observed_at < as_of
    signal = {
        "direction": "UP",
        "raw_direction": "UP",
        "probability_up": 0.7,
        "research_gate_passed": True,
    }
    result = module._settle_signal(
        signal, latent, as_of, 5,
        observed_price=observed_price, observed_at=observed_at,
    )
    assert result is not None
    expected = (float(latent.loc[as_of + module.pd.Timedelta(minutes=5)]) / observed_price - 1) * 100
    assert abs(result["actual_return_pct"] - expected) < 1e-12
    assert result["observation_age_minutes"] > 0
    assert result["observed_price"] == observed_price
    # The latent as_of price is deliberately not the settlement baseline.
    hidden_baseline = (float(latent.loc[as_of + module.pd.Timedelta(minutes=5)]) / float(latent.loc[as_of]) - 1) * 100
    assert abs(result["actual_return_pct"] - hidden_baseline) > 1e-10


def test_full_sparse_scenario_reports_stale_observation_age():
    module = load_module()
    result = module.run_scenario(
        module.Scenario("sparse", 1.0, 0.01, 0.10, bar_probability=0.20),
        seed=99,
        evaluation_step_minutes=5,
    )
    assert any(row["observation_age_minutes"] > 0 for row in result["snapshots"])
    assert all(row["observation_age_minutes"] >= 0 for row in result["snapshots"])


def test_horizon_reporting_separates_abstentions_from_missing_predictions():
    module = load_module()
    result = module.run_scenario(
        module.Scenario("trend_up", 3.0, 0.02, 0.04, volume_scale=1.2),
        seed=7,
        evaluation_step_minutes=30,
    )
    for horizon in ("5", "15", "30"):
        row = result["by_horizon"][horizon]
        assert row["decision_opportunities"] == result["snapshot_count"]
        assert row["samples"] > 0
        assert row["missing_prediction_count"] + row["samples"] == row["decision_opportunities"]
        assert 0.0 <= row["prediction_coverage"] <= 1.0
        assert row["no_trade_count"] + row["trade_signals"] == row["samples"]
        assert abs(row["no_trade_rate"] - (1.0 - row["signal_rate"])) < 1e-12
        assert 0 <= row["raw_direction_sample_count"] <= row["samples"]
        if row["raw_direction_sample_count"]:
            assert 0.0 <= row["raw_direction_accuracy"] <= 1.0
        else:
            assert row["raw_direction_accuracy"] is None


def test_zero_settlements_are_not_reported_as_100_percent_abstention(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "_settle_signal", lambda *args, **kwargs: None)
    result = module.run_scenario(
        module.Scenario("trend_up", 3.0, 0.02, 0.04, volume_scale=1.2),
        seed=7,
        evaluation_step_minutes=30,
    )
    assert result["settlement_count"] == 0
    assert result["no_trade_rate"] is None
    for row in result["by_horizon"].values():
        assert row["samples"] == 0
        assert row["no_trade_rate"] is None
        assert row["raw_direction_accuracy"] is None
        assert row["prediction_coverage"] == 0.0
        assert row["missing_prediction_count"] == row["decision_opportunities"]
