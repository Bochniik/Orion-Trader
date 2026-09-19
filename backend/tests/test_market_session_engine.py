from datetime import datetime, timezone

from app.services.market_session_engine import classify_market_session


def _calendar(day, open_time="09:30", close_time="16:00"):
    return [{"date": day, "open": open_time, "close": close_time}]


def test_regular_session_contract_is_live_and_calendar_aware():
    result = classify_market_session(
        now=datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc),
        clock={
            "is_open": True,
            "next_open": "2026-09-21T13:30:00+00:00",
            "next_close": "2026-09-18T20:00:00+00:00",
        },
        calendar_rows=_calendar("2026-09-18"),
    )
    assert result["mode"] == "regular"
    assert result["workflow_mode"] == "live"
    assert result["price_semantics"] == "live_regular"
    assert result["allowed_workflows"]["live_scanner"] is True
    assert result["allowed_workflows"]["research_lab"] is False
    assert result["next_transition_kind"] == "regular_close"


def test_premarket_is_transition_research_not_live_permission():
    result = classify_market_session(
        now=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        clock={
            "is_open": False,
            "next_open": "2026-09-18T13:30:00+00:00",
            "next_close": "2026-09-18T20:00:00+00:00",
        },
        calendar_rows=_calendar("2026-09-18"),
    )
    assert result["mode"] == "premarket"
    assert result["workflow_mode"] == "transition_research"
    assert result["confirmation_required"] is True
    assert result["allowed_workflows"]["premarket_engine"] is True
    assert result["allowed_workflows"]["live_scanner"] is False
    assert result["next_transition_kind"] == "regular_open"


def test_early_close_uses_calendar_close_for_after_hours_transition():
    result = classify_market_session(
        now=datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc),
        clock={
            "is_open": False,
            "next_open": "2026-11-30T14:30:00+00:00",
        },
        calendar_rows=_calendar("2026-11-27", close_time="13:00"),
    )
    assert result["mode"] == "after_hours"
    assert result["regular_close"].endswith("13:00:00-05:00")
    assert result["workflow_mode"] == "transition_research"
    assert result["allowed_workflows"]["extended_hours_monitoring"] is True


def test_weekend_is_closed_research_with_next_regular_open():
    result = classify_market_session(
        now=datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc),
        clock={
            "is_open": False,
            "next_open": "2026-09-21T13:30:00+00:00",
        },
        calendar_rows=[],
    )
    assert result["mode"] == "closed"
    assert result["workflow_mode"] == "research"
    assert result["ui_priority"] == "research_review_preparation"
    assert result["price_semantics"] == "historical_or_delayed"
    assert result["next_transition_kind"] == "next_regular_open"
    assert result["allowed_workflows"]["settlement_and_evaluation"] is True


def test_holiday_does_not_become_after_hours_without_calendar_session():
    result = classify_market_session(
        now=datetime(2026, 12, 25, 22, 0, tzinfo=timezone.utc),
        clock={
            "is_open": False,
            "next_open": "2026-12-28T14:30:00+00:00",
        },
        calendar_rows=[],
    )
    assert result["mode"] == "closed"
    assert result["calendar_verified"] is False
    assert result["allowed_workflows"]["live_scanner"] is False
    assert result["price_semantics"] == "historical_or_delayed"
