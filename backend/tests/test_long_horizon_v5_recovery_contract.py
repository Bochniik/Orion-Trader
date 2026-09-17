from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts/classify_long_horizon_v5_recovery_contract.py"
    spec = importlib.util.spec_from_file_location("long_horizon_v5_recovery_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


classifier = _load()


def _payload(contract=classifier.EXPECTED_CONTRACT):
    return {"acquisition_provenance": {"contract": contract}}


def test_recovers_supported_contract_even_for_older_artifact():
    assert classifier.classify(_payload(), "2026-09-12T12:00:00Z") == "recover"


@pytest.mark.parametrize("contract", [None, "legacy-contract", ""])
def test_skips_unsupported_pre_contract_history(contract):
    payload = {} if contract is None else _payload(contract)
    assert classifier.classify(payload, "2026-09-13T07:00:32Z") == "skip_pre_contract"


@pytest.mark.parametrize("created_at", ["2026-09-13T07:00:33Z", "2026-09-14T00:00:00Z"])
def test_fails_closed_for_unsupported_contract_at_or_after_boundary(created_at):
    with pytest.raises(ValueError, match="Post-contract"):
        classifier.classify(_payload("legacy-contract"), created_at)


def test_rejects_naive_artifact_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        classifier.classify(_payload(), "2026-09-13T07:00:33")
