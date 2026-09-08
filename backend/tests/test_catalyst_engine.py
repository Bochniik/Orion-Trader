from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.services.catalyst_engine import build_breakout_readiness


NOW = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)


def history(*, strength=1.0, compressed=True, rising_volume=True):
    index = pd.date_range(end=NOW, periods=65, freq="B", tz="UTC")
    close = np.concatenate(
        [np.linspace(80, 100, 44), np.linspace(100, 100 + 6 * strength, 21)]
    )
    wide = np.full(65, 1.0)
    if compressed:
        wide[-10:] = 0.18
    volume = np.full(65, 1_000_000.0)
    if rising_volume:
        volume[-5:] = [1_300_000, 1_400_000, 1_500_000, 1_600_000, 1_700_000]
    return pd.DataFrame(
        {
            "Open": close - 0.05,
            "High": close + wide,
            "Low": close - wide,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def fresh(*names):
    return {name: {"status": "fresh"} for name in names}


def signal(result, signal_id):
    return next(row for row in result["signals"] if row["id"] == signal_id)


def test_complete_observed_evidence_can_reach_high_potential_without_claiming_probability():
    result = build_breakout_readiness(
        "TEST",
        history(strength=1.0),
        benchmark_history=history(strength=0.15),
        profile={
            "float_shares": 8_000_000,
            "short_percent_of_float": 6,
            "sector": "Technology",
        },
        sector_history=history(strength=0.4),
        news={"news": [{
            "title": "Company announces strategic contract",
            "published_at": NOW.timestamp(),
        }]},
        insider_activity={
            "transactions": [{
                "Transaction": "Open market purchase",
                "Start Date": (NOW - timedelta(days=10)).isoformat(),
            }]
        },
        earnings={
            "earnings": [{"Earnings Date": (NOW + timedelta(days=15)).isoformat()}]
        },
        freshness=fresh(
            "history", "benchmark", "profile", "sector", "news",
            "insider", "earnings",
        ),
        now=NOW,
    )

    assert result["score"] == 100
    assert result["coverage_percent"] == 100
    assert result["qualified"] is True
    assert result["status"] == "high_potential"
    assert "not probability" in result["score_meaning"]


def test_missing_evidence_receives_zero_points_and_blocks_high_potential_label():
    result = build_breakout_readiness(
        "TEST",
        history(),
        benchmark_history=history(strength=0.15),
        freshness=fresh("history", "benchmark"),
        now=NOW,
    )

    assert signal(result, "small_float")["available"] is False
    assert signal(result, "small_float")["points"] == 0
    assert signal(result, "insider_buying")["points"] == 0
    assert result["coverage_percent"] == 50
    assert result["qualified"] is False
    assert any("usable evidence" in warning for warning in result["warnings"])


def test_short_interest_is_disclosed_as_risk_and_never_adds_score_points():
    common = dict(
        ticker="TEST",
        history=history(),
        benchmark_history=history(strength=0.15),
        freshness=fresh("history", "benchmark", "profile"),
        now=NOW,
    )
    normal = build_breakout_readiness(
        profile={"float_shares": 30_000_000, "short_percent_of_float": 5},
        **common,
    )
    elevated = build_breakout_readiness(
        profile={"float_shares": 30_000_000, "short_percent_of_float": 32},
        **common,
    )

    assert elevated["score"] == normal["score"]
    assert elevated["microstructure"]["short_percent_of_float"] == 32
    assert any("severe reversal" in warning for warning in elevated["warnings"])


def test_stale_catalyst_feeds_cannot_award_points():
    result = build_breakout_readiness(
        "TEST",
        history(),
        news={"news": [{
            "title": "FDA approval announced",
            "published_at": NOW.timestamp(),
        }]},
        earnings={
            "earnings": [{"Earnings Date": (NOW + timedelta(days=5)).isoformat()}]
        },
        freshness={
            "history": {"status": "fresh"},
            "news": {"status": "stale"},
            "earnings": {"status": "stale"},
        },
        now=NOW,
    )

    catalyst = signal(result, "upcoming_catalyst")
    assert catalyst["available"] is False
    assert catalyst["points"] == 0
    assert result["catalysts"]["headline_matches"] == []
