from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from evals.audit_sector_specialist_leave_one_out import audit_leave_one_out


def _records(days: int = 24):
    sectors = {
        "Information Technology": ("AAPL", "MSFT", "NVDA", "AMD"),
        "Consumer Discretionary": ("AMZN", "TSLA"),
        "Communication Services": ("META", "GOOGL"),
    }
    result = {}
    start = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    for horizon in ("30m", "1h", "3h", "5h"):
        rows = []
        for day in range(days):
            stamp = (start + timedelta(days=day)).isoformat()
            for sector, symbols in sectors.items():
                for symbol in symbols:
                    actual = 1 if sector == "Information Technology" else 0
                    rows.append({"timestamp": stamp, "symbol": symbol, "sector": sector, "p_up": 50.0, "actual_up": actual})
        result[horizon] = rows
    return result


def test_loo_audit_is_non_promotional_and_focuses_long_horizons():
    report = audit_leave_one_out(_records(), min_observations=12, min_sessions=5, bootstrap_samples=30)
    assert report["research_only"] is True
    assert report["screening_only"] is True
    assert report["decisive_holdout"] is False
    assert report["promotion_authorized"] is False
    assert report["focus_horizons"] == ["3h", "5h"]
    assert report["sector_symbols"] == ["AAPL", "AMD", "MSFT", "NVDA"]


def test_every_target_sector_symbol_is_omitted_once_and_scored():
    report = audit_leave_one_out(_records(), min_observations=12, min_sessions=5, bootstrap_samples=30)
    for horizon in ("3h", "5h"):
        row = report["horizons"][horizon]
        assert set(row["omissions"]) == {"AAPL", "AMD", "MSFT", "NVDA"}
        assert row["omission_count"] == 4
        for omitted, metrics in row["omissions"].items():
            assert metrics["candidate_rows_active"] > 0, omitted
            assert metrics["paired_observations"] == metrics["candidate_rows_active"]


def test_audit_fails_closed_when_sector_has_too_few_symbols():
    records = _records()
    for horizon in records:
        records[horizon] = [row for row in records[horizon] if row["symbol"] not in {"NVDA", "AMD"}]
    with pytest.raises(ValueError, match="at least three"):
        audit_leave_one_out(records, min_observations=4, min_sessions=2, bootstrap_samples=10)


def test_audit_rejects_unknown_focus_horizon():
    with pytest.raises(ValueError, match="unsupported focus horizons"):
        audit_leave_one_out(_records(), focus_horizons=("2h",), min_observations=4, min_sessions=2, bootstrap_samples=10)
