from __future__ import annotations

import pytest

from evals.audit_long_horizon_screening_protocol import audit_screening_protocol


def _symbol(symbol: str, *, pairs_3h: int, pairs_5h: int):
    return {
        "symbol": symbol,
        "versus_v3_1": {
            "paired_tournament": {
                "horizons": {
                    "3h": {"paired_observations": pairs_3h},
                    "5h": {"paired_observations": pairs_5h},
                }
            }
        },
    }


def _payload(symbols):
    return {
        "benchmark": {
            "contract": "orion-long-horizon-v5-historical-screen-v1",
            "research_conclusion": "v5_reject_unchanged",
            "symbols": symbols,
        }
    }


def test_frozen_like_geometry_is_inconclusive_not_model_rejection():
    symbols = [_symbol(s, pairs_3h=72, pairs_5h=36) for s in ("AAPL", "MSFT", "NVDA", "AMZN")]
    result = audit_screening_protocol(_payload(symbols), min_observations=80, min_symbols_per_horizon=3)

    assert result["score_blind_audit"] is True
    assert result["protocol_feasible"] is False
    assert result["decision_grade"] is False
    assert result["decision"] == "benchmark_inconclusive_protocol_infeasible"
    assert result["model_disposition"] == "do_not_promote_or_reject_model_from_this_screen"
    assert result["infeasible_horizons"] == ["3h", "5h"]
    assert result["horizons"]["3h"]["capable_symbol_count"] == 0
    assert result["horizons"]["5h"]["max_paired_observations"] == 36
    assert result["runtime_modified"] is False


def test_protocol_is_feasible_when_enough_symbols_can_meet_coverage_gate():
    symbols = [
        _symbol("AAPL", pairs_3h=100, pairs_5h=90),
        _symbol("MSFT", pairs_3h=95, pairs_5h=85),
        _symbol("NVDA", pairs_3h=90, pairs_5h=80),
        _symbol("AMZN", pairs_3h=20, pairs_5h=10),
    ]
    result = audit_screening_protocol(_payload(symbols), min_observations=80, min_symbols_per_horizon=3)

    assert result["protocol_feasible"] is True
    assert result["decision_grade"] is True
    assert result["decision"] == "protocol_feasible"
    assert result["infeasible_horizons"] == []


def test_protocol_audit_is_score_blind():
    payload = _payload([_symbol("AAPL", pairs_3h=100, pairs_5h=100)] * 3)
    payload["benchmark"]["versus_v3_1"] = {
        "horizons": {
            "3h": {"weighted_brier_improvement": -999.0},
            "5h": {"weighted_log_loss_improvement": 999.0},
        }
    }
    result = audit_screening_protocol(payload, min_observations=80, min_symbols_per_horizon=3)
    assert result["protocol_feasible"] is True


def test_unknown_contract_fails_closed():
    with pytest.raises(ValueError, match="unsupported benchmark contract"):
        audit_screening_protocol({"contract": "wrong"})
