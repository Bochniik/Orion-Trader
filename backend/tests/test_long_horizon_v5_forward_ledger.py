from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCRIPT_PATH = ROOT / "scripts" / "evaluate_long_horizon_v5_forward_ledger.py"
SPEC = importlib.util.spec_from_file_location("evaluate_long_horizon_v5_forward_ledger", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

TOURNAMENT_PATH = BACKEND / "evals" / "intraday_challenger_tournament.py"
TOURNAMENT_SPEC = importlib.util.spec_from_file_location("symbol_aware_tournament", TOURNAMENT_PATH)
TOURNAMENT = importlib.util.module_from_spec(TOURNAMENT_SPEC)
assert TOURNAMENT_SPEC and TOURNAMENT_SPEC.loader
sys.modules[TOURNAMENT_SPEC.name] = TOURNAMENT
TOURNAMENT_SPEC.loader.exec_module(TOURNAMENT)


def _record(*, role: str, horizon: str, day: int, index: int, symbol: str = "AAPL", probability: float = 0.6):
    prediction = f"2026-09-{11 + day:02d}T14:{index * 5:02d}:00+00:00"
    hours = 3 if horizon == "3h" else 5
    target_hour = 17 + hours - 3
    target = f"2026-09-{11 + day:02d}T{target_hour:02d}:{index * 5:02d}:00+00:00"
    actual = (day + index) % 2
    engine = MODULE.INCUMBENT_ENGINE if role == "incumbent" else MODULE.CHALLENGER_ENGINE
    return {
        "engine": engine,
        "symbol": symbol,
        "horizon": horizon,
        "prediction_time_utc": prediction,
        "target_time_utc": target,
        "probability_up": probability,
        "predicted_direction": "UP" if probability >= 0.5 else "DOWN",
        "actual_up": actual,
        "base_price": 100.0,
        "outcome_price": 101.0 if actual else 99.0,
        "realized_return_pct": 1.0 if actual else -1.0,
        "correct_direction": bool((probability >= 0.5) == bool(actual)),
        "brier": (probability - actual) ** 2,
        "log_loss": 0.5,
        "lineage": {"paired_role": role},
        "material_sha256": f"{role}-{horizon}-{day}-{index}-{symbol}",
    }


def _ledger(*, sessions: int, rows_per_session: int = 10):
    records = []
    for horizon in MODULE.LONG_HORIZONS:
        for day in range(sessions):
            for index in range(rows_per_session):
                records.append(_record(role="incumbent", horizon=horizon, day=day, index=index, probability=0.55))
                records.append(_record(role="challenger", horizon=horizon, day=day, index=index, probability=0.65))
    return {"contract": MODULE.LEDGER_CONTRACT, "records": records}


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_immature_ledger_is_score_blind_and_does_not_run_tournament(tmp_path, monkeypatch):
    path = _write(tmp_path, _ledger(sessions=3, rows_per_session=10))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("tournament must not run before score-blind maturity")

    monkeypatch.setattr(MODULE, "evaluate_long_horizon_candidate", fail_if_called)
    result = MODULE.evaluate_ledger(path)

    assert result["decision_grade"] is False
    assert result["metrics_exposed"] is False
    assert result["research_conclusion"] == "forward_holdout_collecting_evidence"
    assert "paired_tournament" not in result
    assert result["forward_sample_readiness"]["horizons"]["3h"]["paired_observations"] == 30


def test_mature_ledger_calls_frozen_forward_gate_once(tmp_path, monkeypatch):
    path = _write(tmp_path, _ledger(sessions=8, rows_per_session=10))
    calls = []

    def fake_gate(incumbent, challenger, **kwargs):
        calls.append((incumbent, challenger, kwargs))
        return {
            "research_conclusion": "long_horizon_challenger_not_demonstrated",
            "forward_research_eligible": False,
            "paired_tournament": {"contract": "test-tournament"},
        }

    monkeypatch.setattr(MODULE, "evaluate_long_horizon_candidate", fake_gate)
    result = MODULE.evaluate_ledger(path)

    assert result["decision_grade"] is True
    assert result["metrics_exposed"] is True
    assert result["research_conclusion"] == "long_horizon_challenger_not_demonstrated"
    assert len(calls) == 1
    incumbent, challenger, kwargs = calls[0]
    assert kwargs["evidence_mode"] == "forward_holdout"
    assert kwargs["min_observations"] == 80
    assert kwargs["min_sessions"] == 8
    assert len(incumbent["prediction_records"]["3h"]) == 80
    assert len(challenger["prediction_records"]["5h"]) == 80


def test_incomplete_pair_fails_closed(tmp_path):
    payload = _ledger(sessions=1, rows_per_session=1)
    payload["records"].pop()
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="Incomplete incumbent/challenger pairs"):
        MODULE.evaluate_ledger(path)


def test_pre_registration_record_fails_closed(tmp_path):
    payload = _ledger(sessions=1, rows_per_session=1)
    payload["records"][0]["prediction_time_utc"] = "2026-09-10T20:00:00+00:00"
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="Pre-registration observation"):
        MODULE.evaluate_ledger(path)


def test_settlement_mismatch_fails_closed(tmp_path):
    payload = _ledger(sessions=1, rows_per_session=1)
    payload["records"][1]["outcome_price"] = 102.0
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="Settlement mismatch"):
        MODULE.evaluate_ledger(path)


def test_tournament_pairs_same_timestamp_across_multiple_symbols():
    timestamp = "2026-09-12T14:00:00+00:00"
    incumbent = [
        {"symbol": "AAPL", "timestamp": timestamp, "actual_up": 1, "p_up": 60},
        {"symbol": "MSFT", "timestamp": timestamp, "actual_up": 0, "p_up": 40},
    ]
    challenger = [
        {"symbol": "AAPL", "timestamp": timestamp, "actual_up": 1, "p_up": 70},
        {"symbol": "MSFT", "timestamp": timestamp, "actual_up": 0, "p_up": 30},
    ]
    paired = TOURNAMENT.pair_records(incumbent, challenger)
    assert len(paired) == 2
    assert {row.symbol for row in paired} == {"AAPL", "MSFT"}
