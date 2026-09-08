"""Offline regression tests for staged discovery, not market-performance claims."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.services.staged_market_scanner import (
    SCORE_MEANING, ScannerConfig, StagedMarketScanner, activity_score,
)


NOW = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


def screening(**overrides):
    return {
        "company_name": "Synthetic research fixture", "price": 100.0,
        "data_timestamp": (NOW - timedelta(seconds=10)).isoformat(),
        "quote_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
        "history_as_of": "2026-08-24T00:00:00+00:00", "history_sessions": 20,
        "average_dollar_volume": 500_000_000, "dollar_volume": 250_000_000,
        "relative_volume": 3.0, "intraday_return": .04,
        "spread_pct": .02, "liquidity_score": 95,
        "provider": "mock_alpaca", "feed": "iex", "data_status": "complete",
        "warnings": ["Synthetic data only."], **overrides,
    }


def context(features=None, **overrides):
    return {
        "feature_snapshot": {
            "timestamp": (NOW - timedelta(minutes=1)).isoformat(), "price": 99.5,
            "features": features or {"return_1m": .004, "return_3m": .008,
                                      "return_5m": .012, "relative_strength_market": .006,
                                      "distance_from_vwap": .01, "rsi_14": 70},
            "source_resolution_seconds": 60, "feature_coverage_percent": 80,
        },
        "history_bars": 120, "provider": "mock_yahoo", "delayed": True,
        "warnings": ["Delayed minute features."],
        "provenance": {"normalization": "minute-start + 60 seconds"}, **overrides,
    }


class RecordingSource:
    def __init__(self, rows, contexts=None):
        self.rows = deepcopy(rows)
        self.contexts = deepcopy(contexts) if contexts is not None else {s: context() for s in rows}
        self.screen_batches, self.feature_batches = [], []

    def stock_universe(self):
        return {"tickers": list(self.rows), "source": "mock_tradable_universe", "complete_us_universe": False}

    def load_screening_batch(self, tickers, *, now):
        assert now == NOW
        self.screen_batches.append(list(tickers))
        return {"rows": {s: self.rows[s] for s in tickers if s in self.rows}}

    def load_feature_snapshots(self, tickers, *, now):
        self.feature_batches.append(list(tickers))
        return {"rows": {s: self.contexts[s] for s in tickers if s in self.contexts}}


class RecordingAnalyzer:
    def __init__(self):
        self.calls = []

    def __call__(self, ticker, screen, ctx, horizons, *, now):
        self.calls.append(ticker)
        bearish = ctx["feature_snapshot"]["features"].get("return_5m", 0) < 0
        return {"model_calls": len(horizons), "results": [
            {"model_direction": "DOWN" if bearish else "UP", "directional_confidence": 73.0,
             "probability_up": .17 if bearish else .73, "probability_down": .73 if bearish else .17,
             "probability_neutral": .10, "model_agreement": 80.0,
             "expected_horizon": horizon, "final_decision": "NO_TRADE", "actionable": False,
             "reasons": ["Synthetic model fixture."], "warnings": ["Model is experimental."]}
            for horizon in horizons
        ]}


def scan(rows, contexts=None, config=None, tickers=None):
    source, analyzer = RecordingSource(rows, contexts), RecordingAnalyzer()
    result = StagedMarketScanner(source, analyzer, config).scan_market(tickers, now=NOW)
    return result, source, analyzer


@pytest.mark.parametrize("fields", [
    {"price": 4.99}, {"average_dollar_volume": 24_999_999},
    {"dollar_volume": 999_999}, {"spread_pct": .3001},
])
def test_illiquid_stock_rejected_before_features_or_model(fields):
    result, source, analyzer = scan({"ILLIQ": screening(**fields)})
    assert result["candidates"] == []
    assert result["exclusion_counts"]["liquidity"] == 1
    assert source.feature_batches == analyzer.calls == []


def test_high_liquidity_and_exact_thresholds_are_accepted():
    result, _, analyzer = scan({"LIQUID": screening(price=5, average_dollar_volume=25_000_000,
                                                     dollar_volume=1_000_000, spread_pct=.30)})
    assert analyzer.calls == ["LIQUID"]
    assert result["candidates"][0]["liquidity"]["eligible"] is True


@pytest.mark.parametrize("fields,reason", [
    ({"price": None}, "missing_price"), ({"price": float("nan")}, "missing_price"),
    ({"provider": None}, "missing_provider"), ({"dollar_volume": -1}, "missing_dollar_volume"),
    ({"liquidity_score": 101}, "invalid_liquidity_score"),
    ({"spread_pct": -1}, "invalid_spread"),
    ({"data_timestamp": "2026-08-25T15:27:59+00:00"}, "snapshot_stale"),
    ({"data_timestamp": "2026-08-25T15:30:01+00:00"}, "snapshot_future"),
    ({"data_timestamp": "2026-08-25T15:30:00"}, "snapshot_unavailable"),
    ({"history_as_of": "2026-08-01T00:00:00+00:00"}, "daily_history_stale"),
    ({"history_sessions": 9}, "insufficient_daily_history"),
])
def test_missing_stale_or_malformed_screening_data_rejected(fields, reason):
    result, source, analyzer = scan({"BAD": screening(**fields)})
    assert result["candidates"] == []
    assert result["exclusion_counts"]["data_quality:" + reason] == 1
    assert source.feature_batches == analyzer.calls == []


def test_unavailable_spread_is_not_invented_or_made_mandatory():
    result, _, _ = scan({"LIQUID": screening(spread_pct=None)})
    candidate = result["candidates"][0]
    assert candidate["liquidity"]["spread_pct"] is None
    assert "spread_pct" in candidate["data_quality"]["missing_fields"]
    assert any("Spread unavailable" in warning for warning in candidate["warnings"])


def test_activity_prefers_unusual_volume_and_is_direction_neutral():
    ordinary = activity_score(screening(relative_volume=1, intraday_return=0))["score"]
    bullish = activity_score(screening(relative_volume=3, intraday_return=.04))["score"]
    bearish = activity_score(screening(relative_volume=3, intraday_return=-.04))["score"]
    assert ordinary == 0 < bullish == bearish == 100


def test_inactive_stock_is_removed_before_minute_history():
    result, source, analyzer = scan({"IDLE": screening(relative_volume=1, intraday_return=0)})
    assert result["exclusion_counts"]["activity:weak_activity"] == 1
    assert source.feature_batches == analyzer.calls == []


@pytest.mark.parametrize("sign,direction", [(1, "UP"), (-1, "DOWN")])
def test_bullish_and_bearish_momentum_reach_existing_analysis(sign, direction):
    ctx = context({"return_1m": .004 * sign, "return_3m": .008 * sign, "return_5m": .012 * sign})
    result, _, analyzer = scan({"MOVE": screening()}, {"MOVE": ctx})
    assert analyzer.calls == ["MOVE"]
    candidate = result["candidates"][0]
    assert "momentum_candidate" in candidate["setup_tags"]
    assert candidate["model_direction"] == direction
    assert candidate["final_decision"] == "NO_TRADE"
    assert candidate["directional_confidence"] == 73


def test_dislocation_reaches_analysis_without_claiming_reversal_or_bargain():
    ctx = context({"return_1m": 0, "return_3m": 0, "return_5m": 0,
                   "distance_from_vwap": -.03, "rsi_14": 15})
    result, _, analyzer = scan({"EXTENDED": screening()}, {"EXTENDED": ctx})
    assert analyzer.calls == ["EXTENDED"]
    candidate = result["candidates"][0]
    assert "dislocation_candidate" in candidate["setup_tags"]
    assert "momentum_candidate" not in candidate["setup_tags"]
    assert "not a bargain or reversal prediction" in candidate["fast_signal_audit"]["semantics"]


@pytest.mark.parametrize("issue", ["stale", "future", "short", "missing", "weak", "low_coverage"])
def test_poor_minute_features_are_rejected_before_inference(issue):
    ctx = context()
    if issue in {"stale", "future"}:
        ctx["feature_snapshot"]["timestamp"] = (NOW + timedelta(seconds=1) if issue == "future" else NOW - timedelta(minutes=21)).isoformat()
    elif issue == "short":
        ctx["history_bars"] = 29
    elif issue == "missing":
        ctx["feature_snapshot"]["features"] = {}
    elif issue == "low_coverage":
        ctx["feature_snapshot"]["feature_coverage_percent"] = 10
    else:
        ctx["feature_snapshot"]["features"] = {"return_3m": .0001, "return_5m": .0001}
    result, _, analyzer = scan({"BAD": screening()}, {"BAD": ctx})
    assert result["candidates"] == []
    assert analyzer.calls == []


def test_opportunity_ranks_evidence_without_replacing_model_probabilities():
    rows = {"STRONG": screening(), "WEAK": screening(liquidity_score=65, relative_volume=1.5, intraday_return=.01)}
    contexts = {"STRONG": context(), "WEAK": context({"return_1m": .001, "return_3m": .003, "return_5m": .005})}
    result, _, _ = scan(rows, contexts)
    strong, weak = result["candidates"]
    assert (strong["ticker"], weak["ticker"]) == ("STRONG", "WEAK")
    assert strong["opportunity_score"] == 90.7 > weak["opportunity_score"]
    assert strong["probability_up"] == weak["probability_up"] == .73
    assert strong["score_semantics"] == result["score_semantics"] == SCORE_MEANING
    assert "not probability of profit" in strong["opportunity_score_audit"]["semantics"]
    assert "probability" not in strong["opportunity_score_audit"]


def test_empty_universe_or_no_qualifying_symbols_is_explicit():
    for rows in ({}, {"ILLIQ": screening(average_dollar_volume=1)}):
        result, _, analyzer = scan(rows)
        assert result["status"] == "no_high_quality_candidates"
        assert result["candidates"] == []
        assert analyzer.calls == []


def test_full_universe_is_paged_and_expensive_work_is_strictly_bounded():
    rows = {f"S{i:04d}": screening() for i in range(3000)}
    result, source, analyzer = scan(rows)
    counts = result["stage_counts"]
    assert counts == {
        "universe_count": 3000, "screened_count": 1000, "valid_data_count": 1000,
        "liquidity_eligible_count": 1000, "activity_eligible_count": 1000,
        "activity_candidates": 100, "valid_feature_count": 100,
        "fast_eligible_count": 100, "fast_candidates": 30, "analysis_attempted": 15,
        "fully_analyzed": 15, "model_evaluations": 15, "returned": 10,
    }
    assert len(source.screen_batches) == 10
    assert len(source.feature_batches) == 1 and len(source.feature_batches[0]) == 100
    assert len(analyzer.calls) == 15
    assert result["universe"]["next_offset"] == 1000
    assert result["universe"]["coverage_complete_for_supplied_universe"] is False
    assert result["capacity_exclusions"] == {"activity": 900, "fast": 70, "analysis": 15}


def test_configurable_reductions_and_multiple_horizons_are_respected():
    cfg = replace(ScannerConfig(), universe_limit=12, snapshot_batch_size=4,
                  activity_limit=8, fast_limit=5, analysis_limit=3, return_limit=2, horizons=("1m", "5m"))
    result, source, analyzer = scan({f"S{i:02d}": screening() for i in range(12)}, config=cfg)
    assert len(source.feature_batches[0]) == 8
    assert len(analyzer.calls) == 3
    assert result["stage_counts"]["model_evaluations"] == 6
    assert result["stage_counts"]["returned"] == 2


def test_general_iterable_normalization_duplicates_and_page_continuation():
    source, analyzer = RecordingSource({s: screening() for s in ("AAA", "BBB", "CCC")}), RecordingAnalyzer()
    cfg = replace(ScannerConfig(), universe_limit=2, activity_limit=2, fast_limit=2, analysis_limit=2, return_limit=2)
    scanner = StagedMarketScanner(source, analyzer, cfg)
    first = scanner.scan_market(iter([" bbb ", "aaa", "AAA", "CCC", "bad/ticker", None]), now=NOW)
    assert first["universe"]["duplicate_symbols"] == 1
    assert first["universe"]["invalid_symbols"] == 2
    second = scanner.scan_market(["AAA", "BBB", "CCC"], now=NOW, universe_offset=first["universe"]["next_offset"])
    assert [c["ticker"] for c in second["candidates"]] == ["CCC"]
    assert second["universe"]["next_offset"] is None
    assert first["universe"]["complete_us_universe"] is False


def test_stage_counts_and_exclusions_account_for_filters():
    rows = {"GOOD": screening(), "MISSING": {}, "ILLIQ": screening(average_dollar_volume=1),
            "IDLE": screening(relative_volume=1, intraday_return=0), "WEAK": screening()}
    contexts = {s: context() for s in rows}
    contexts["WEAK"] = context({"return_3m": 0, "return_5m": 0})
    result, _, analyzer = scan(rows, contexts)
    counts = result["stage_counts"]
    assert [counts[k] for k in ("universe_count", "valid_data_count", "liquidity_eligible_count", "activity_candidates",
                                "fast_candidates", "fully_analyzed", "returned")] == [5, 4, 3, 2, 1, 1, 1]
    assert analyzer.calls == ["GOOD"]
    assert {k: result["exclusion_counts"][k] for k in ("data_quality", "liquidity", "activity", "fast")} == dict.fromkeys(("data_quality", "liquidity", "activity", "fast"), 1)


def test_provenance_and_delayed_freshness_survive_json_serialization():
    result, _, _ = scan({"GOOD": screening()})
    row = json.loads(json.dumps(result, allow_nan=False))["candidates"][0]
    assert row["provider"] == "mock_alpaca" and row["feed"] == "iex"
    assert row["feature_provider"] == "mock_yahoo" and row["delayed"] is True
    assert row["data_timestamp"] == screening()["data_timestamp"]
    assert row["quote_timestamp"] == screening()["quote_timestamp"]
    assert row["freshness"]["snapshot"]["age_seconds"] == 10
    assert row["freshness"]["features"]["age_seconds"] == 60
    assert row["current_price"] == 100 and row["model_reference_price"] == 99.5
    assert row["data_quality"]["provenance"] == context()["provenance"]


def test_identical_inputs_produce_identical_ranked_output():
    rows = {"BBB": screening(), "AAA": screening()}
    first, _, _ = scan(rows)
    second, _, _ = scan(dict(reversed(list(rows.items()))))
    assert first == second


def test_live_scan_freshness_uses_retrieval_time_not_an_old_scan_start():
    clock = {"now": NOW}

    class ArrivingSource(RecordingSource):
        def load_screening_batch(self, tickers, *, now):
            # A live snapshot is legitimately newer than the scan's start.
            clock["now"] = NOW + timedelta(seconds=15)
            row = screening(data_timestamp=clock["now"].isoformat())
            return {"rows": {s: row for s in tickers}}

    scanner = StagedMarketScanner(ArrivingSource({"LIVE": screening()}), RecordingAnalyzer(),
                                  clock=lambda: clock["now"])
    result = scanner.scan_market()
    assert [row["ticker"] for row in result["candidates"]] == ["LIVE"]
    assert result["generated_at"] == clock["now"].isoformat()
    assert result["candidates"][0]["freshness"]["snapshot"]["age_seconds"] == 0


def test_snapshot_that_ages_out_during_feature_fetch_is_not_analyzed():
    clock = {"now": NOW}

    class SlowFeatureSource(RecordingSource):
        def load_screening_batch(self, tickers, *, now):
            return {"rows": {s: self.rows[s] for s in tickers}}

        def load_feature_snapshots(self, tickers, *, now):
            clock["now"] = NOW + timedelta(minutes=3)
            return {"rows": {s: self.contexts[s] for s in tickers}}

    analyzer = RecordingAnalyzer()
    scanner = StagedMarketScanner(SlowFeatureSource({"AGED": screening()}), analyzer,
                                  clock=lambda: clock["now"])
    result = scanner.scan_market()
    assert result["candidates"] == []
    assert analyzer.calls == []
    assert result["exclusion_counts"]["pre_analysis:snapshot_stale"] == 1


def test_inference_failure_does_not_abort_unrelated_finalists():
    source, analyzer = RecordingSource({s: screening() for s in ("BAD", "GOOD")}), RecordingAnalyzer()

    def fail_one(ticker, *args, **kwargs):
        if ticker == "BAD":
            raise ValueError("test failure")
        return analyzer(ticker, *args, **kwargs)

    result = StagedMarketScanner(source, fail_one).scan_market(now=NOW)
    assert [c["ticker"] for c in result["candidates"]] == ["GOOD"]
    assert result["partial_failure"] is True


def test_malformed_model_output_is_not_a_candidate():
    source, analyzer = RecordingSource({"BAD": screening()}), RecordingAnalyzer()

    def malformed(*args, **kwargs):
        out = analyzer(*args, **kwargs)
        out["results"][0]["probability_up"] = .99
        return out

    result = StagedMarketScanner(source, malformed).scan_market(now=NOW)
    assert result["candidates"] == []
    assert result["exclusion_counts"]["analysis:invalid_probability_contract"] == 1


@pytest.mark.parametrize("changes", [{"analysis_limit": 101}, {"return_limit": 20},
                                      {"snapshot_batch_size": 201}, {"minimum_price": -1},
                                      {"horizons": ("2m",)}, {"universe_limit": True}])
def test_invalid_scanner_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(ScannerConfig(), **changes)
