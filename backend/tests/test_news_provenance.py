import pytest

from backend.app.services.news_provenance import build_causal_news_audit, validate_news_provenance


def _row(**overrides):
    row = {
        "published_at": "2026-01-01T12:00:00+00:00",
        "received_at": "2026-01-01T12:00:01+00:00",
        "processed_at": "2026-01-01T12:00:02+00:00",
    }
    row.update(overrides)
    return row


def test_causal_news_passes_only_when_processed_before_observation():
    result = validate_news_provenance(
        _row(), observation_time_utc="2026-01-01T12:00:03+00:00"
    )
    assert result["causal_at_observation"] is True
    assert result["reason_codes"] == []


def test_future_processed_news_fails_closed():
    audit = build_causal_news_audit(
        [_row(processed_at="2026-01-01T12:00:04+00:00")],
        observation_time_utc="2026-01-01T12:00:03+00:00",
    )
    assert audit["status"] == "INSUFFICIENT_DATA"
    assert "row_0:processed_after_observation" in audit["diagnostics"]


def test_missing_news_provenance_is_insufficient_data():
    audit = build_causal_news_audit([], observation_time_utc="2026-01-01T12:00:03+00:00")
    assert audit["status"] == "INSUFFICIENT_DATA"
    assert audit["observations"] == 0


@pytest.mark.parametrize("field", ["published_at", "received_at", "processed_at"])
def test_missing_timestamp_never_becomes_causal(field):
    row = _row()
    row[field] = None
    audit = build_causal_news_audit([row], observation_time_utc="2026-01-01T12:00:03+00:00")
    assert audit["status"] == "INSUFFICIENT_DATA"
    assert audit["validated_observations"] == 0


def test_timezone_offsets_are_normalized_before_causal_comparison():
    audit = build_causal_news_audit(
        [{
            "published_at": "2026-01-01T13:00:00+01:00",
            "received_at": "2026-01-01T13:00:01+01:00",
            "processed_at": "2026-01-01T13:00:02+01:00",
        }],
        observation_time_utc="2026-01-01T12:00:03+00:00",
    )
    assert audit["status"] == "PASS"
