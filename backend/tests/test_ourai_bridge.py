"""Fail-closed Orion backend integration tests for OurAI loopback evidence."""
from __future__ import annotations

from types import SimpleNamespace
import httpx

from app.api import intelligence_routes as intelligence
from app.services import ourai_bridge


def sample():
    return {
        "schema_version": 1,
        "source": "ourai_verified_forward_journal",
        "experiment": "frozen_v3_magnitude_15m",
        "mode": "RESEARCH_SHADOW_ONLY",
        "trading_enabled": False,
        "horizon_minutes": 15,
        "direction_available": False,
        "journal_valid": True,
        "evaluated_at_utc": "2026-10-20T14:05:00Z",
        "prediction_count": 2,
        "resolution_count": 1,
        "pending_count": 1,
        "overdue_pending_count": 0,
        "champion_mae_bps": 8.7,
        "linear_mae_bps": 9.7,
        "null_mae_bps": 10.5,
        "symbols": {"NVDA": {
            "predictions": 2, "resolved": 1, "pending": 1,
            "overdue_pending": 0, "champion_mae_bps": 8.7,
            "linear_mae_bps": 9.7, "null_mae_bps": 10.5,
        }},
        "latest_by_symbol": {"NVDA": {
            "symbol": "NVDA", "predicted_at": "2026-10-20T14:00:20Z",
            "sample_timestamp": "2026-10-20T14:00:00Z",
            "target_due_at": "2026-10-20T14:15:00Z",
            "expected_magnitude_bps": 12.0, "resolved": False,
        }},
    }


def transport_response(data, status=200):
    def respond(request):
        assert request.url.host == "127.0.0.1"
        assert request.url.path == ourai_bridge.ROUTE
        assert request.url.port == 8765
        return httpx.Response(status, json=data)
    return httpx.MockTransport(respond)


def test_disabled_default_never_contacts_network(monkeypatch):
    monkeypatch.delenv("OURAI_BRIDGE_ENABLED", raising=False)
    def fail(_request):
        raise AssertionError("Network attempted while disabled")
    result = ourai_bridge.fetch_ourai_forward_evidence(transport=httpx.MockTransport(fail))
    assert result["status"] == "disabled"
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False


def test_valid_magnitude_evidence_is_sanitized():
    data = sample()
    data["secret"] = "never-return-this"
    data["direction"] = "UP"
    data["p_up"] = 0.999
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, port=8765, transport=transport_response(data),
    )
    assert result["status"] == "available"
    assert result["resolution_count"] == 1
    assert result["champion_mae_bps"] == 8.7
    assert result["symbols"]["NVDA"]["resolved"] == 1
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "secret" not in result and "direction" not in result and "p_up" not in result
    assert "decision" not in result and "trade" not in result


def test_wrong_semantics_or_invalid_counts_fail_closed():
    for mutation in (
        {"direction_available": True},
        {"mode": "LIVE_TRADING"},
        {"journal_valid": False},
        {"prediction_count": 10},
        {"champion_mae_bps": float("nan")},
    ):
        data = sample()
        data.update(mutation)
        out = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, transport=transport_response(data),
        )
        assert out["status"] == "unavailable"
        assert "champion_mae_bps" not in out


def test_missing_service_invalid_port_and_empty_evidence_fail_closed():
    out = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response({"status": "unavailable"}, status=503),
    )
    assert out["status"] == "unavailable"
    assert ourai_bridge.fetch_ourai_forward_evidence(enabled=True, port=99999)["status"] == "unavailable"
    data = sample()
    data["resolution_count"] = 0
    data["pending_count"] = 2
    data["symbols"]["NVDA"]["resolved"] = 0
    data["symbols"]["NVDA"]["pending"] = 2
    data["champion_mae_bps"] = 8.7
    out = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data)
    )
    assert out["status"] == "unavailable"


def test_intelligence_route_requires_user_scope_and_calls_bridge(monkeypatch):
    seen = []
    monkeypatch.setattr(ourai_bridge, "fetch_ourai_forward_evidence", lambda: seen.append(1) or {"status": "disabled"})
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "single-local-user"}))
    response = intelligence.ourai_forward_evidence(request)
    assert response["status"] == "disabled"
    assert seen == [1]


def test_overdue_symbol_total_mismatch_fails_closed():
    data = sample()
    data["overdue_pending_count"] = 1
    assert ourai_bridge.fetch_ourai_forward_evidence(enabled=True, transport=transport_response(data))["status"] == "unavailable"


def test_symbol_mae_must_match_resolved_count():
    data = sample()
    data["symbols"]["NVDA"]["champion_mae_bps"] = None
    assert ourai_bridge.fetch_ourai_forward_evidence(enabled=True, transport=transport_response(data))["status"] == "unavailable"
    data = sample()
    data["symbols"]["NVDA"]["resolved"] = 0
    data["symbols"]["NVDA"]["pending"] = 2
    data["resolution_count"] = 0
    data["pending_count"] = 2
    for key in ("champion_mae_bps", "linear_mae_bps", "null_mae_bps"):
        data[key] = None
    assert ourai_bridge.fetch_ourai_forward_evidence(enabled=True, transport=transport_response(data))["status"] == "unavailable"


def test_latest_forecast_chronology_fails_closed():
    for field, bad_time in (
        ("predicted_at", "2026-10-20T13:59:59Z"),
        ("predicted_at", "2026-10-20T14:15:00Z"),
        ("target_due_at", "2026-10-20T13:59:00Z"),
    ):
        data = sample()
        data["latest_by_symbol"]["NVDA"][field] = bad_time
        result = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, transport=transport_response(data),
        )
        assert result["status"] == "unavailable"
        assert "latest_by_symbol" not in result


def test_upstream_connection_failure_and_timeout_fail_closed():
    for error in (httpx.ConnectError("connection refused"), httpx.ReadTimeout("upstream timed out")):
        def fail(request):
            raise error
        result = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, transport=httpx.MockTransport(fail),
        )
        assert result["status"] == "unavailable"
        assert result["direction_available"] is False
        assert result["trading_enabled"] is False
        assert "symbols" not in result


def test_resolved_global_evidence_requires_all_three_mae_metrics():
    for key in ("champion_mae_bps", "linear_mae_bps", "null_mae_bps"):
        data = sample()
        data[key] = None
        result = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, transport=transport_response(data),
        )
        assert result["status"] == "unavailable"
        assert "champion_mae_bps" not in result


def test_unresolved_evidence_without_mae_is_valid():
    data = sample()
    data["resolution_count"] = 0
    data["pending_count"] = 2
    data["symbols"]["NVDA"]["resolved"] = 0
    data["symbols"]["NVDA"]["pending"] = 2
    for key in ("champion_mae_bps", "linear_mae_bps", "null_mae_bps"):
        data[key] = None
        data["symbols"]["NVDA"][key] = None
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "available"
    assert result["resolution_count"] == 0
    assert result["champion_mae_bps"] is None
    assert result["direction_available"] is False
