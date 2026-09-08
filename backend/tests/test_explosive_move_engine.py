from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.services.adaptive_risk import build_adaptive_risk_plan
from app.services.explosive_move_engine import (
    build_explosive_move_assessment,
    classify_catalyst_events,
)


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def daily_history(strength=1.0):
    index = pd.date_range(end=NOW, periods=100, freq="B", tz="UTC")
    close = np.concatenate([
        np.linspace(80, 100, 80),
        np.linspace(100, 103 * strength, 20),
    ])
    ranges = np.full(100, 1.0)
    ranges[-8:] = 0.22
    volume = np.full(100, 1_000_000.0)
    volume[-5:] = [1_300_000, 1_500_000, 1_700_000, 1_900_000, 2_100_000]
    return pd.DataFrame({
        "Open": close - 0.05,
        "High": close + ranges,
        "Low": close - ranges,
        "Close": close,
        "Volume": volume,
    }, index=index)


def intraday_history():
    index = pd.date_range(end=NOW, periods=30, freq="5min", tz="UTC")
    close = np.linspace(104, 105.8, 30)
    volume = np.full(30, 20_000.0)
    volume[-3:] = [60_000, 80_000, 100_000]
    return pd.DataFrame({
        "Open": close - 0.05,
        "High": close + 0.5,
        "Low": close - 0.5,
        "Close": close,
        "Volume": volume,
    }, index=index)


def freshness(filings="fresh"):
    return {
        name: {"status": "fresh"}
        for name in ("daily", "intraday", "benchmark", "sector", "profile", "news", "events")
    } | {
        "filings": {"status": filings},
        "corporate_actions": {"status": "fresh"},
    }


def assessment(**overrides):
    values = {
        "symbol": "TEST",
        "daily_history": daily_history(),
        "intraday_history": intraday_history(),
        "benchmark_history": daily_history(0.90),
        "sector_history": daily_history(0.95),
        "profile": {
            "asset_type": "Stock",
            "market_cap": 1_000_000_000,
            "float_shares": 30_000_000,
            "short_percent_of_float": 12,
            "short_ratio": 2.5,
            "sector": "Technology",
            "industry": "Software",
        },
        "candidate": {"price": 105.8, "spread_percent": 0.08},
        "news": {"news": [{
            "id": 7,
            "headline": "Company announces major strategic contract",
            "created_at": (NOW - timedelta(minutes=5)).isoformat(),
            "symbols": ["TEST"],
        }]},
        "filings": {"filings": []},
        "corporate_actions": {"corporate_actions": {}},
        "freshness": freshness(),
        "now": NOW,
    }
    values.update(overrides)
    return build_explosive_move_assessment(**values)


def test_three_scores_remain_separate_and_probabilities_fail_closed():
    result = assessment()

    assert 0 <= result["pre_move_score"]["score"] <= 100
    assert 0 <= result["ignition_score"]["score"] <= 100
    assert 0 <= result["danger_score"]["score"] <= 100
    assert "not a calibrated probability" in result["pre_move_score"]["score_meaning"]
    assert "not a calibrated probability" in result["danger_score"]["score_meaning"]
    assert result["probability_estimates"]["status"] == "not_calibrated"
    assert all(
        value is None
        for key, value in result["probability_estimates"].items()
        if key not in {"status", "explanation"}
    )


def test_dilution_and_reverse_split_risk_suppresses_bullish_watch_state():
    result = assessment(
        filings={"filings": [
            {
                "form": "S-3",
                "filing_date": NOW.date().isoformat(),
                "acceptance_datetime": NOW.isoformat(),
                "accession_number": "0001",
            },
            {
                "form": "424B5",
                "filing_date": NOW.date().isoformat(),
                "acceptance_datetime": NOW.isoformat(),
                "accession_number": "0002",
            },
        ]},
        corporate_actions={"corporate_actions": {
            "reverse_splits": [{"id": "rs-1", "ex_date": NOW.date().isoformat()}],
        }},
        danger_threshold=50,
    )

    assert result["danger_score"]["score"] >= 50
    assert result["decision"] == "NO_TRADE"
    assert any("Danger Score" in item for item in result["blockers"])


def test_registration_filing_raises_danger_without_reclassifying_large_cap_as_distressed():
    result = assessment(
        profile={
            "asset_type": "Stock",
            "market_cap": 50_000_000_000,
            "float_shares": 1_000_000_000,
            "sector": "Technology",
            "industry": "Software",
            "short_percent_of_float": 2,
            "short_ratio": 1,
            "first_trade_date": "2000-01-01T00:00:00Z",
        },
        filings={"filings": [{
            "form": "S-3",
            "filing_date": NOW.date().isoformat(),
            "accession_number": "shelf-1",
        }]},
    )

    assert result["category"]["primary"] == "liquid_large_cap"
    assert result["danger_score"]["score"] >= 25


def test_generic_fda_or_earnings_headline_is_not_assigned_positive_sentiment():
    events = classify_catalyst_events(
        "TEST",
        news={"news": [{
            "headline": "Company schedules earnings and FDA meeting",
            "created_at": "2026-08-01T12:00:00Z",
        }]},
        now=NOW,
    )

    assert events[0]["sentiment"] == "unknown"
    assert events[0]["source_id"].startswith("news-")


def test_high_risk_category_requires_fresh_sec_metadata():
    result = assessment(
        profile={
            "asset_type": "Stock",
            "market_cap": 80_000_000,
            "float_shares": 4_000_000,
            "short_percent_of_float": 18,
            "sector": "Healthcare",
            "industry": "Biotechnology",
        },
        filings=None,
        freshness=freshness("unavailable"),
    )

    assert result["category"]["primary"] == "low_float_momentum"
    assert result["decision"] == "NO_TRADE"
    assert any("SEC filing metadata" in item for item in result["blockers"])


def test_absent_freshness_metadata_never_counts_as_fresh_evidence():
    result = assessment(freshness={})

    assert result["decision"] == "NO_TRADE"
    assert result["pre_move_score"]["evidence_coverage_percent"] < 55
    assert any("evidence coverage" in item for item in result["blockers"])


def test_event_records_reaction_latency_and_does_not_infer_filing_contents():
    events = classify_catalyst_events(
        "TEST",
        filings={"filings": [{
            "form": "8-K",
            "filing_date": NOW.date().isoformat(),
            "acceptance_datetime": (NOW - timedelta(seconds=3)).isoformat(),
            "accession_number": "abc",
        }]},
        now=NOW,
    )

    assert events[0]["classification"] == "material_event_filing"
    assert events[0]["sentiment"] == "unknown"
    assert events[0]["reaction_latency_seconds"] == 3
    assert "contents were not inferred" in events[0]["explanation"]


def test_adaptive_risk_is_unlevered_and_rejects_no_trade():
    safe = assessment()
    plan = build_adaptive_risk_plan(
        safe,
        account_equity=100_000,
        available_cash=50_000,
        maximum_risk_percent=0.5,
    )

    assert plan["maximum_permitted_leverage"] <= 1
    assert plan["requested_leverage"] <= 1
    assert plan["safety_boundary"].startswith("Shadow/research")

    rejected = assessment(
        filings=None,
        freshness=freshness("unavailable"),
        profile={
            "asset_type": "Stock",
            "market_cap": 50_000_000,
            "float_shares": 3_000_000,
            "sector": "Healthcare",
            "industry": "Biotechnology",
        },
    )
    rejected_plan = build_adaptive_risk_plan(
        rejected,
        account_equity=100_000,
        available_cash=50_000,
    )
    assert rejected_plan["status"] == "REJECT_TRADE"
    assert rejected_plan["shares"] == 0
    assert rejected_plan["maximum_permitted_leverage"] == 0


def test_drawdown_reduces_risk_instead_of_recovery_leverage():
    safe = assessment()
    normal = build_adaptive_risk_plan(
        safe, account_equity=100_000, available_cash=100_000,
        maximum_risk_percent=0.5, portfolio_drawdown_percent=0,
    )
    drawdown = build_adaptive_risk_plan(
        safe, account_equity=100_000, available_cash=100_000,
        maximum_risk_percent=0.5, portfolio_drawdown_percent=11,
    )

    assert drawdown["recommended_position_value"] <= normal["recommended_position_value"]
    assert drawdown["risk_per_trade_percent"] < normal["risk_per_trade_percent"]
    assert drawdown["maximum_permitted_leverage"] <= normal["maximum_permitted_leverage"]
