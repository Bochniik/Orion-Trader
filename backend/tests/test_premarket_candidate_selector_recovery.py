from datetime import datetime, timezone

from app.services.premarket_candidate_selector import screen_premarket_candidates


NOW = datetime(2026, 10, 7, 12, 30, tzinfo=timezone.utc)  # 08:30 ET


class SparseLatestBarBroker:
    def __init__(self):
        self.latest_calls = []
        self.history_calls = []

    def latest_stock_bars(self, user_id, symbols, *, feed):
        self.latest_calls.append((user_id, tuple(symbols), feed))
        # Simulate Alpaca latest-bar sparsity: MSFT has no latest-bar row even
        # though consolidated minute history exists.
        return {
            "bars": {
                "AAPL": {
                    "c": 260.0,
                    "t": "2026-10-07T12:24:00Z",
                }
            }
        }

    def delayed_premarket_bars(
        self,
        user_id,
        symbols,
        *,
        now,
        timeframe,
        safe_delay_seconds,
    ):
        self.history_calls.append(
            (user_id, tuple(symbols), now, timeframe, safe_delay_seconds)
        )
        return {
            "bars": {
                "MSFT": [
                    {
                        "o": 501.0,
                        "h": 502.0,
                        "l": 500.0,
                        "c": 501.5,
                        "v": 1000,
                        "t": "2026-10-07T12:05:00Z",
                    },
                    {
                        "o": 501.5,
                        "h": 503.0,
                        "l": 501.0,
                        "c": 502.5,
                        "v": 1500,
                        "t": "2026-10-07T12:14:00Z",
                    },
                ]
            }
        }


def test_missing_latest_bar_is_recovered_from_delayed_sip_minute_history():
    broker = SparseLatestBarBroker()
    observations = {
        "AAPL": {"close": 258.0, "dollar_volume": 2_000_000_000},
        "MSFT": {"close": 500.0, "dollar_volume": 1_500_000_000},
    }

    result = screen_premarket_candidates(
        broker,
        "alice",
        observations,
        now=NOW,
        pool_limit=2,
        finalist_limit=2,
        maximum_age_minutes=30,
    )

    by_symbol = {row["ticker"]: row for row in result["items"]}

    assert result["status"] == "candidates_available"
    assert set(by_symbol) == {"AAPL", "MSFT"}
    assert by_symbol["AAPL"]["price_source"] == "latest_bar"
    assert by_symbol["MSFT"]["price_source"] == "delayed_sip_minute_history"
    assert by_symbol["MSFT"]["premarket_price"] == 502.5
    assert by_symbol["MSFT"]["gap_pct"] == 0.5
    assert result["history_recovery_attempted"] is True
    assert result["history_missing_symbol_count"] == 1
    assert result["history_recovered_count"] == 1
    assert result["history_request_count"] == 1
    assert broker.history_calls[0][1] == ("MSFT",)
    assert broker.history_calls[0][3:] == ("1Min", 960)


def test_history_recovery_failure_stays_fail_closed_and_diagnostic():
    class BrokenHistoryBroker(SparseLatestBarBroker):
        def latest_stock_bars(self, user_id, symbols, *, feed):
            return {"bars": {}}

        def delayed_premarket_bars(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    result = screen_premarket_candidates(
        BrokenHistoryBroker(),
        "alice",
        {"MSFT": {"close": 500.0, "dollar_volume": 1_500_000_000}},
        now=NOW,
        pool_limit=1,
        finalist_limit=1,
    )

    assert result["status"] == "no_current_premarket_candidates"
    assert result["items"] == []
    assert result["history_recovery_attempted"] is True
    assert result["history_recovered_count"] == 0
    assert result["provider_failure_count"] == 1
    assert result["provider_failures"][0]["stage"] == "delayed_premarket_bars"
    assert result["rejected"][0]["reason"] == "no_delayed_sip_premarket_bar"
