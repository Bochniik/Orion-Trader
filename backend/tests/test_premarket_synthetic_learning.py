from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def load_module():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    path = scripts_dir / "run_premarket_synthetic_learning.py"
    spec = importlib.util.spec_from_file_location("premarket_synthetic_learning", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_seed_split_rejects_overlap():
    module = load_module()
    with pytest.raises(ValueError, match="development_lockbox_seed_overlap"):
        module.validate_seed_split((1, 2, 3), (3, 4))


def test_seed_manifest_is_deterministic_and_role_scoped():
    module = load_module()
    a = module._seed_manifest((1, 2, 3), role="development")
    b = module._seed_manifest((1, 2, 3), role="development")
    c = module._seed_manifest((1, 2, 3), role="untouched_lockbox")
    assert a == b
    assert a["sha256"] != c["sha256"]


def test_learning_loop_is_research_only_and_keeps_lockbox_untouched():
    module = load_module()
    payload = module.run_learning_loop(
        development_seeds=(11,),
        lockbox_seeds=(101,),
        evaluation_step_minutes=15,
    )
    assert payload["contract"] == module.CONTRACT
    assert payload["research_only"] is True
    assert payload["synthetic_evidence_only"] is True
    assert payload["runtime_routing_enabled"] is False
    assert payload["automatic_promotion_allowed"] is False
    assert payload["live_forward_validation_required"] is True
    assert set(payload["development_manifest"]["seeds"]).isdisjoint(payload["lockbox_manifest"]["seeds"])
    assert payload["development_sample_count"] > 0
    assert payload["lockbox_sample_count"] > 0
    assert payload["challenger"]["research_only"] is True
    assert payload["challenger"]["runtime_routing_enabled"] is False
    assert payload["lockbox_evaluation"]["production_eligible"] is False


def test_challenger_training_is_deterministic_for_same_rows():
    module = load_module()
    rows = module.collect_synthetic_dataset(
        seeds=(11,),
        evaluation_step_minutes=15,
        scenarios=(module.SCENARIOS[0], module.SCENARIOS[1]),
    )
    first = module.train_challenger(rows)
    second = module.train_challenger(rows)
    assert first == second
    assert set(first["targets"]) == {"5", "15", "30"}


def test_lockbox_gate_cannot_make_challenger_production_eligible():
    module = load_module()
    development = module.collect_synthetic_dataset(
        seeds=(11,),
        evaluation_step_minutes=15,
        scenarios=(module.SCENARIOS[0], module.SCENARIOS[1]),
    )
    challenger = module.train_challenger(development)
    lockbox = module.collect_synthetic_dataset(
        seeds=(101,),
        evaluation_step_minutes=15,
        scenarios=(module.SCENARIOS[0], module.SCENARIOS[1]),
    )
    evaluation = module.evaluate_lockbox(lockbox, challenger)
    assert evaluation["production_eligible"] is False
    assert evaluation["live_forward_validation_required"] is True
    assert evaluation["verdict"] in {"RESEARCH_VALIDATED_SYNTHETIC", "REJECTED_OR_INSUFFICIENT_SYNTHETIC"}
