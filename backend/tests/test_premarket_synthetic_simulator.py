from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "simulate_premarket_market.py"
    spec = importlib.util.spec_from_file_location("premarket_synthetic_simulator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
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
