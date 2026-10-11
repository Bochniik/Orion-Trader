from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.frozen_symbol_specialist_engine import FrozenSymbolSpecialistEngine
from evals.benchmark_nvda_specialist_v1 import evaluate_horizon


def _records(*, sessions: int = 30, rows_per_symbol_session: int = 12):
    symbols = {
        "NVDA": "Information Technology",
        "AMD": "Information Technology",
        "MSFT": "Information Technology",
        "AAPL": "Information Technology",
        "META": "Communication Services",
        "GOOGL": "Communication Services",
        "TSLA": "Consumer Discretionary",
        "AMZN": "Consumer Discretionary",
    }
    start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    rows = []
    for day in range(sessions):
        session_start = start + timedelta(days=day)
        for symbol, sector in symbols.items():
            for index in range(rows_per_symbol_session):
                ts = session_start + timedelta(minutes=5 * index)
                actual = 1 if (index + day) % 3 else 0
                base = 0.58 if actual else 0.46
                if symbol == "NVDA":
                    base = 0.54 if actual else 0.49
                rows.append({
                    "timestamp": ts.isoformat(),
                    "symbol": symbol,
                    "sector": sector,
                    "p_up": base,
                    "actual_up": actual,
                })
    return rows


def test_engine_freezes_symbol_specific_offset_and_predicts_without_mutation():
    rows = _records(sessions=20)
    model = FrozenSymbolSpecialistEngine.fit(
        rows,
        symbol="NVDA",
        sector="Information Technology",
        horizon="30m",
        min_global_obs=100,
        min_global_sessions=10,
        min_sector_obs=80,
        min_sector_sessions=8,
        min_symbol_obs=60,
        min_symbol_sessions=8,
    )
    first = model.predict(0.55)
    second = model.predict(0.55)
    assert first == second
    assert model.symbol == "NVDA"
    assert model.research_only is True
    assert model.automatic_live_promotion is False
    assert model.runtime_influence_allowed is False
    assert model.model_id.startswith("orion-frozen-symbol-specialist-v1:NVDA:30m:")


def test_engine_fails_closed_without_enough_symbol_sessions():
    rows = _records(sessions=4)
    with pytest.raises(RuntimeError, match="symbol development evidence"):
        FrozenSymbolSpecialistEngine.fit(
            rows,
            symbol="NVDA",
            sector="Information Technology",
            horizon="30m",
            min_global_obs=1,
            min_global_sessions=1,
            min_sector_obs=1,
            min_sector_sessions=1,
            min_symbol_obs=1,
            min_symbol_sessions=8,
        )


def test_nvda_benchmark_uses_latest_ten_sessions_as_untouched_lockbox():
    result = evaluate_horizon(_records(sessions=30), horizon="30m")
    assert result["development_sessions"] == 20
    assert len(result["lockbox_sessions"]) == 10
    assert result["lockbox_samples"] == 120
    assert result["engine"]["development_last_session"] < result["lockbox_sessions"][0]
    assert result["research_only"] is True
    assert result["automatic_live_promotion"] is False
    assert result["verdict"] in {"REJECTED", "AWAITING_MORE_EVIDENCE", "RESEARCH_VALIDATED"}
