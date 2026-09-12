from __future__ import annotations

from datetime import datetime, timedelta, timezone

from evals.benchmark_sector_specialists import screen_records


def _records(days: int = 24):
    sectors = {
        "Information Technology": ("AAPL", "MSFT", "NVDA", "AMD"),
        "Consumer Discretionary": ("AMZN", "TSLA"),
        "Communication Services": ("META", "GOOGL"),
    }
    by_horizon = {}
    start = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
    for horizon in ("30m", "1h", "3h", "5h"):
        rows = []
        for day in range(days):
            stamp = (start + timedelta(days=day)).isoformat()
            for sector, symbols in sectors.items():
                for symbol in symbols:
                    actual = 1 if sector == "Information Technology" else 0
                    rows.append(
                        {
                            "timestamp": stamp,
                            "symbol": symbol,
                            "sector": sector,
                            "p_up": 50.0,
                            "actual_up": actual,
                        }
                    )
        by_horizon[horizon] = rows
    return by_horizon


def test_historical_screen_is_non_promotional_and_horizon_partitioned():
    report = screen_records(_records(), min_observations=12, min_sessions=5, bootstrap_samples=50)
    assert report["research_only"] is True
    assert report["screening_only"] is True
    assert report["decisive_holdout"] is False
    assert report["promotion_authorized"] is False
    assert report["horizon_partitioned"] is True
    assert set(report["horizons"]) == {"30m", "1h", "3h", "5h"}


def test_each_sector_is_scored_separately_on_active_rows():
    report = screen_records(_records(), min_observations=12, min_sessions=5, bootstrap_samples=50)
    expected = {"Information Technology", "Consumer Discretionary", "Communication Services"}
    for horizon in report["horizons"].values():
        assert set(horizon["sectors"]) == expected
        for sector in expected:
            row = horizon["sectors"][sector]
            assert row["candidate_rows_active"] > 0
            assert row["candidate_rows_total"] >= row["candidate_rows_active"]
            assert row["paired_observations"] == row["candidate_rows_active"]
            assert row["minimum_observations"] == 12
            assert row["minimum_sessions"] == 5


def test_sector_screen_does_not_pool_horizons():
    records = _records()
    records["30m"] = records["30m"][:40]
    report = screen_records(records, min_observations=4, min_sessions=2, bootstrap_samples=20)
    assert report["horizons"]["30m"]["input_observations"] == 40
    assert report["horizons"]["1h"]["input_observations"] > 40
