from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = _load("long_horizon_v5_collection_health", "scripts/audit_long_horizon_v5_collection_health.py")


def _payload(*, as_of_et: str, status: str, horizons: list[str], symbols: list[str], missing=None, reason=None):
    missing = list(missing or [])
    expected = len(symbols) * len(horizons)
    return {
        "contract": audit.PREDICTION_CONTRACT,
        "status": status,
        "session_gate": {
            "as_of_et": as_of_et,
            "eligible_horizons": horizons,
            "reason": reason,
        },
        "symbols_requested": symbols,
        "coverage": {
            "score_blind": True,
            "expected_pair_count": expected,
            "observed_pair_count": expected - len(missing),
            "complete": not missing,
            "missing_pairs": missing,
        },
        "paired_predictions": [],
        "failures": {},
    }


def test_collection_health_aggregates_only_operational_coverage():
    complete = _payload(
        as_of_et="2026-09-11T10:05:00-04:00",
        status="completed",
        horizons=["3h", "5h"],
        symbols=["AAPL", "MSFT"],
    )
    degraded = _payload(
        as_of_et="2026-09-11T11:05:00-04:00",
        status="degraded",
        horizons=["3h"],
        symbols=["AAPL", "MSFT"],
        missing=[{"symbol": "MSFT", "horizon": "3h"}],
    )
    skipped = _payload(
        as_of_et="2026-09-11T13:05:00-04:00",
        status="skipped",
        horizons=[],
        symbols=["AAPL", "MSFT"],
        reason="no_settleable_horizon_before_regular_close",
    )

    report = audit.build_health_report([complete, degraded, skipped])

    assert report["score_blind"] is True
    assert report["metrics_exposed"] is False
    assert report["artifact_count"] == 3
    assert report["eligible_run_count"] == 2
    assert report["complete_run_count"] == 1
    assert report["degraded_run_count"] == 1
    assert report["skipped_run_count"] == 1
    assert report["distinct_session_count"] == 1
    assert report["coverage"]["expected_pair_count"] == 6
    assert report["coverage"]["observed_pair_count"] == 5
    assert report["coverage"]["missing_pair_count"] == 1
    assert report["coverage"]["coverage_fraction"] == pytest.approx(5 / 6, abs=1e-6)
    assert report["coverage"]["by_horizon"]["3h"]["expected_pair_count"] == 4
    assert report["coverage"]["by_horizon"]["3h"]["observed_pair_count"] == 3
    assert report["coverage"]["by_horizon"]["5h"]["expected_pair_count"] == 2
    assert report["coverage"]["by_horizon"]["5h"]["observed_pair_count"] == 2
    assert report["coverage"]["missing_by_symbol"] == {"MSFT": 1}
    assert report["critical_5h"]["eligible_run_count"] == 1
    assert report["critical_5h"]["complete_run_count"] == 1
    assert report["critical_5h"]["coverage_fraction"] == 1.0
    assert report["skip_reasons"] == {"no_settleable_horizon_before_regular_close": 1}


def test_collection_health_is_invariant_to_probabilities_outcomes_and_scores():
    base = _payload(
        as_of_et="2026-09-11T10:05:00-04:00",
        status="completed",
        horizons=["3h", "5h"],
        symbols=["AAPL"],
    )
    altered = deepcopy(base)
    altered["paired_predictions"] = [{
        "symbol": "AAPL",
        "horizon": "5h",
        "incumbent": {"probability_up": 0.01, "direction": "bearish"},
        "challenger": {"probability_up": 0.99, "direction": "bullish"},
        "realized_outcome": 1,
        "brier": 0.0001,
        "log_loss": 0.01,
        "accuracy": 1.0,
        "ece": 0.0,
    }]
    altered["failures"] = {"ignored": "also not part of score-blind health"}

    assert audit.build_health_report([base]) == audit.build_health_report([altered])

    serialized = json.dumps(audit.build_health_report([altered]), sort_keys=True).lower()
    for forbidden in ("probability_up", "realized_outcome", "brier", "log_loss", "accuracy", "ece"):
        assert forbidden not in serialized


def test_collection_health_is_deterministic_across_input_order():
    first = _payload(
        as_of_et="2026-09-11T10:05:00-04:00",
        status="completed",
        horizons=["3h", "5h"],
        symbols=["AAPL", "MSFT"],
    )
    second = _payload(
        as_of_et="2026-09-12T10:05:00-04:00",
        status="degraded",
        horizons=["3h", "5h"],
        symbols=["AAPL", "MSFT"],
        missing=[{"symbol": "AAPL", "horizon": "5h"}],
    )
    assert audit.build_health_report([first, second]) == audit.build_health_report([second, first])


def test_collection_health_fails_closed_on_inconsistent_or_non_score_blind_coverage():
    wrong_contract = _payload(
        as_of_et="2026-09-11T10:05:00-04:00",
        status="completed",
        horizons=["3h"],
        symbols=["AAPL"],
    )
    wrong_contract["contract"] = "unexpected"
    with pytest.raises(audit.CollectionHealthError, match="contract"):
        audit.build_health_report([wrong_contract])

    exposed = _payload(
        as_of_et="2026-09-11T10:05:00-04:00",
        status="completed",
        horizons=["3h"],
        symbols=["AAPL"],
    )
    exposed["coverage"]["score_blind"] = False
    with pytest.raises(audit.CollectionHealthError, match="score-blind"):
        audit.build_health_report([exposed])

    inconsistent = _payload(
        as_of_et="2026-09-11T10:05:00-04:00",
        status="completed",
        horizons=["3h"],
        symbols=["AAPL"],
    )
    inconsistent["coverage"]["observed_pair_count"] = 0
    with pytest.raises(audit.CollectionHealthError, match="observed_pair_count"):
        audit.build_health_report([inconsistent])
