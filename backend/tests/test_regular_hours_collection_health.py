from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.audit_regular_hours_collection_health import (
    CollectionHealthError,
    PREDICTIVE_LINEAGE_FILES,
    PREREGISTERED_SYMBOLS,
    build_health_report,
)


def _lineage(seed: str = "a") -> dict:
    return {
        "git_commit": seed * 40,
        "files_sha256": {path: seed * 64 for path in PREDICTIVE_LINEAGE_FILES},
    }


def _artifact(
    *,
    as_of_et: str = "2026-09-11T10:05:00-04:00",
    provenance_gap: str | None = None,
    retry_symbol: str | None = None,
    failed_symbol: str | None = None,
    lineage_seed: str = "a",
) -> dict:
    symbols = list(PREREGISTERED_SYMBOLS)
    rows = {}
    failures = {}
    for symbol in symbols:
        if symbol == failed_symbol:
            failures[symbol] = "RuntimeError: provider unavailable"
            continue
        aligned = symbol != provenance_gap
        attempts = 2 if symbol == retry_symbol else 1
        rows[symbol] = {
            "symbol": symbol,
            "available": True,
            "as_of": "2026-09-11T14:05:00+00:00" if aligned else None,
            "source_timestamp_aligned": aligned,
            "source_as_of": {
                "v1": "2026-09-11T14:05:00+00:00",
                "v2": "2026-09-11T14:05:00+00:00" if aligned else "2026-09-11T14:10:00+00:00",
            },
            "alignment_attempts": attempts,
            "horizons": {
                "30m": {"probability_up": 99.0, "probability_down": 1.0, "direction": "bullish"},
            },
        }

    available = len(rows)
    provenance_valid = sum(
        row["source_timestamp_aligned"] and bool(row["as_of"])
        for row in rows.values()
    )
    retries = sum(int(row["alignment_attempts"]) > 1 for row in rows.values())
    attempts = sum(int(row["alignment_attempts"]) for row in rows.values())
    return {
        "contract": "orion-regular-hours-cloud-shadow-v2",
        "runner_version": "regular-hours-v3-1-cloud-shadow-v2",
        "created_at_utc": "2026-09-11T14:05:10+00:00",
        "session_gate": {
            "allowed": True,
            "as_of_et": as_of_et,
            "weekday": 4,
            "nyse_trading_day": True,
            "window_et": "09:30-15:30",
            "reason": None,
        },
        "symbols_requested": symbols,
        "research_only": True,
        "order_submission_enabled": False,
        "runtime_modified": False,
        "lineage": _lineage(lineage_seed),
        "status": "completed",
        "results": {
            "symbol_count": len(symbols),
            "available_symbol_count": available,
            "provenance_valid_symbol_count": provenance_valid,
            "provenance_valid_coverage_pct": 100.0 * provenance_valid / len(symbols),
            "alignment_retry_symbol_count": retries,
            "alignment_attempt_count": attempts,
            "failure_count": len(failures),
            "symbols": rows,
            "failures": failures,
        },
    }


def test_report_measures_provenance_retries_and_failures_without_scores() -> None:
    report = build_health_report(
        [_artifact(provenance_gap="AAPL", retry_symbol="MSFT", failed_symbol="NVDA")]
    )

    assert report["contract"] == "orion-regular-hours-collection-health-v2"
    assert report["score_blind"] is True
    assert report["metrics_exposed"] is False
    assert report["standard_universe_artifact_count"] == 1
    assert report["distinct_standard_session_count"] == 1
    assert report["coverage"]["requested_symbol_count"] == 10
    assert report["coverage"]["available_symbol_count"] == 9
    assert report["coverage"]["provenance_valid_symbol_count"] == 8
    assert report["coverage"]["provenance_gap_symbol_count"] == 2
    assert report["coverage"]["failure_count"] == 1
    assert report["coverage"]["alignment_retry_symbol_count"] == 1
    assert report["coverage"]["alignment_attempt_count"] == 10
    assert report["coverage"]["provenance_valid_fraction"] == 0.8
    assert report["coverage"]["alignment_retry_fraction"] == 0.1
    assert len(report["predictive_lineage_artifact_counts"]) == 1
    assert report["latest_standard_predictive_lineage_sha256"]


def test_report_is_invariant_to_predictive_probability_and_direction_changes() -> None:
    original = _artifact()
    changed = deepcopy(original)
    for row in changed["results"]["symbols"].values():
        row["horizons"] = {
            "30m": {"probability_up": 1.0, "probability_down": 99.0, "direction": "bearish"},
            "5h": {"probability_up": 73.0, "probability_down": 27.0, "direction": "bullish"},
        }

    assert build_health_report([changed]) == build_health_report([original])


def test_predictive_lineage_change_is_visible_without_reading_scores() -> None:
    first = _artifact(as_of_et="2026-09-10T10:05:00-04:00", lineage_seed="a")
    second = _artifact(as_of_et="2026-09-11T10:05:00-04:00", lineage_seed="b")
    report = build_health_report([first, second])

    assert len(report["predictive_lineage_artifact_counts"]) == 2
    assert len(report["predictive_lineage_sessions"]) == 2
    assert report["latest_standard_predictive_lineage_sha256"] in report["predictive_lineage_sessions"]
    assert report["by_session"]["2026-09-10"]["predictive_lineages"] != report["by_session"]["2026-09-11"]["predictive_lineages"]


def test_missing_predictive_lineage_fails_closed() -> None:
    artifact = _artifact()
    del artifact["lineage"]
    with pytest.raises(CollectionHealthError, match="missing lineage"):
        build_health_report([artifact])


def test_malformed_predictive_lineage_digest_fails_closed() -> None:
    artifact = _artifact()
    path = PREDICTIVE_LINEAGE_FILES[0]
    artifact["lineage"]["files_sha256"][path] = "not-a-sha"
    with pytest.raises(CollectionHealthError, match="SHA-256"):
        build_health_report([artifact])


def test_skipped_artifacts_are_counted_but_do_not_reduce_market_coverage() -> None:
    skipped = _artifact()
    skipped["status"] = "skipped"
    skipped["reason"] = "outside_regular_hours_shadow_window"
    skipped["session_gate"]["allowed"] = False
    skipped["session_gate"]["as_of_et"] = "2026-09-11T18:45:00-04:00"
    skipped["session_gate"]["reason"] = "outside_regular_hours_shadow_window"
    skipped["results"] = {}

    report = build_health_report([_artifact(), skipped])
    assert report["artifact_count"] == 2
    assert report["skipped_artifact_count"] == 1
    assert report["skip_reasons"] == {"outside_regular_hours_shadow_window": 1}
    assert report["coverage"]["requested_symbol_count"] == 10
    assert report["coverage"]["provenance_valid_fraction"] == 1.0


def test_nonstandard_universe_is_visible_but_excluded_from_standard_coverage() -> None:
    custom = _artifact()
    keep = {"AAPL", "MSFT"}
    custom["symbols_requested"] = ["AAPL", "MSFT"]
    custom["results"]["symbols"] = {
        symbol: row for symbol, row in custom["results"]["symbols"].items() if symbol in keep
    }
    custom["results"].update(
        {
            "symbol_count": 2,
            "available_symbol_count": 2,
            "provenance_valid_symbol_count": 2,
            "provenance_valid_coverage_pct": 100.0,
            "alignment_retry_symbol_count": 0,
            "alignment_attempt_count": 2,
            "failure_count": 0,
            "failures": {},
        }
    )

    report = build_health_report([custom])
    assert report["nonstandard_universe_artifact_count"] == 1
    assert report["standard_universe_artifact_count"] == 0
    assert report["coverage"]["requested_symbol_count"] == 0
    assert report["coverage"]["provenance_valid_fraction"] is None
    assert report["latest_standard_predictive_lineage_sha256"] is None


def test_report_fails_closed_when_reported_operational_counts_are_inconsistent() -> None:
    artifact = _artifact()
    artifact["results"]["provenance_valid_symbol_count"] = 9
    with pytest.raises(CollectionHealthError, match="provenance_valid_symbol_count"):
        build_health_report([artifact])


def test_legacy_v1_artifacts_are_explicitly_excluded_from_v2_coverage() -> None:
    legacy = _artifact()
    legacy["runner_version"] = "regular-hours-v3-1-cloud-shadow-v1"
    legacy["contract"] = "orion-regular-hours-cloud-shadow-v1"
    legacy.pop("lineage", None)
    for row in legacy["results"]["symbols"].values():
        row.pop("source_timestamp_aligned", None)
        row.pop("source_as_of", None)
        row.pop("alignment_attempts", None)

    report = build_health_report([legacy, _artifact()])
    assert report["artifact_count"] == 2
    assert report["legacy_excluded_artifact_count"] == 1
    assert report["legacy_excluded_runner_versions"] == {
        "regular-hours-v3-1-cloud-shadow-v1": 1
    }
    assert report["standard_universe_artifact_count"] == 1
    assert report["coverage"]["requested_symbol_count"] == 10
    assert report["coverage"]["provenance_valid_fraction"] == 1.0
