"""Fail-closed Orion backend integration tests for OurAI loopback evidence."""
from __future__ import annotations

from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from contextlib import contextmanager
import json
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
    # MockTransport must expose an unread byte stream for iter_raw().
    # httpx.Response(json=... / content=...) preloads the body and raises
    # StreamConsumed when the production bridge uses streaming reads.
    def respond(request):
        assert request.url.host == "127.0.0.1"
        assert request.url.path == ourai_bridge.ROUTE
        assert request.url.port == 8765
        return httpx.Response(
            status,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(json.dumps(data).encode("utf-8")),
        )
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


@contextmanager
def local_forward_http_server(payload, status=200):
    """Real loopback HTTP transport with synthetic producer-schema data."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == ourai_bridge.ROUTE
            assert self.headers["Host"].startswith("127.0.0.1:")
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_loopback_http_contract_sanitizes_synthetic_producer_snapshot():
    """Exercise the actual httpx network path instead of MockTransport."""
    data = sample()
    data["p_up"] = 0.99
    data["api_key"] = "never-expose"
    with local_forward_http_server(data) as port:
        result = ourai_bridge.fetch_ourai_forward_evidence(enabled=True, port=port)
    assert result["status"] == "available"
    assert result["source"] == "ourai_verified_forward_journal"
    assert result["symbols"]["NVDA"]["predictions"] == 2
    assert result["latest_by_symbol"]["NVDA"]["expected_magnitude_bps"] == 12.0
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "p_up" not in result
    assert "api_key" not in result


def test_real_loopback_http_unavailable_and_disabled_do_not_expose_stale_evidence():
    with local_forward_http_server({"status": "forward_evidence_unavailable"}, status=503) as port:
        unavailable = ourai_bridge.fetch_ourai_forward_evidence(enabled=True, port=port)
        disabled = ourai_bridge.fetch_ourai_forward_evidence(enabled=False, port=port)
    assert unavailable["status"] == "unavailable"
    assert "symbols" not in unavailable
    assert "latest_by_symbol" not in unavailable
    assert disabled["status"] == "disabled"
    assert disabled["trading_enabled"] is False


def test_forward_evidence_endpoint_rejects_missing_user_before_bridge(monkeypatch):
    calls = []
    monkeypatch.setattr(ourai_bridge, "fetch_ourai_forward_evidence", lambda: calls.append(1) or sample())
    for user in (None, {}, {"id": ""}):
        request = SimpleNamespace(state=SimpleNamespace(user=user))
        with pytest.raises(HTTPException) as exc:
            intelligence.ourai_forward_evidence(request)
        assert exc.value.status_code == 401
    assert calls == []


def test_latest_forecast_must_correspond_to_a_real_symbol_prediction():
    data = sample()
    data["latest_by_symbol"] = {}
    assert ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data)
    )["status"] == "unavailable"

    data = sample()
    data["prediction_count"] = 0
    data["resolution_count"] = 0
    data["pending_count"] = 0
    data["symbols"]["NVDA"]["predictions"] = 0
    data["symbols"]["NVDA"]["resolved"] = 0
    data["symbols"]["NVDA"]["pending"] = 0
    for key in ("champion_mae_bps", "linear_mae_bps", "null_mae_bps"):
        data[key] = None
        data["symbols"]["NVDA"][key] = None
    assert ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data)
    )["status"] == "unavailable"


def test_latest_resolution_state_must_match_symbol_counts():
    data = sample()
    data["resolution_count"] = 0
    data["pending_count"] = 2
    data["symbols"]["NVDA"]["resolved"] = 0
    data["symbols"]["NVDA"]["pending"] = 2
    data["latest_by_symbol"]["NVDA"]["resolved"] = True
    for key in ("champion_mae_bps", "linear_mae_bps", "null_mae_bps"):
        data[key] = None
        data["symbols"]["NVDA"][key] = None
    assert ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data)
    )["status"] == "unavailable"

    data = sample()
    data["resolution_count"] = 2
    data["pending_count"] = 0
    data["symbols"]["NVDA"]["resolved"] = 2
    data["symbols"]["NVDA"]["pending"] = 0
    data["latest_by_symbol"]["NVDA"]["resolved"] = False
    assert ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data)
    )["status"] == "unavailable"


def test_bridge_distinguishes_transport_http_and_invalid_evidence_failures():
    cases = (
        (httpx.ConnectError("getaddrinfo failed"), "upstream_connection_failure"),
        (httpx.ConnectTimeout("WinError 10060"), "upstream_connection_failure"),
        (httpx.ReadTimeout("timed out"), "upstream_connection_failure"),
    )
    for error, reason in cases:
        def fail(_request):
            raise error
        result = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, transport=httpx.MockTransport(fail),
        )
        assert result["status"] == "unavailable"
        assert result["unavailable_reason"] == reason
        assert result["trading_enabled"] is False
        assert "symbols" not in result and "latest_by_symbol" not in result

    http_failure = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response({"status": "unavailable"}, status=503),
    )
    assert http_failure["unavailable_reason"] == "upstream_http_failure"
    malformed = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response({"journal_valid": False}),
    )
    assert malformed["unavailable_reason"] == "invalid_upstream_evidence"
    assert "symbols" not in malformed


@pytest.mark.parametrize(
    "error",
    [
        httpx.WriteTimeout("write timed out"),
        httpx.WriteError("socket write failed"),
        httpx.PoolTimeout("connection pool unavailable"),
        httpx.LocalProtocolError("invalid upstream protocol"),
        httpx.RemoteProtocolError("upstream protocol failed"),
    ],
)
def test_all_loopback_transport_failures_are_unavailable_not_model_errors(error):
    """Synthetic network failures must never publish stale model evidence."""
    def fail(_request):
        raise error

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(fail),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "upstream_connection_failure"
    assert result["mode"] == "RESEARCH_SHADOW_ONLY"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result
    assert "champion_mae_bps" not in result
    assert str(error) not in str(result)


def test_oversized_loopback_json_fails_closed_without_exposing_data():
    payload = sample()
    payload["secret"] = "private-" + "x" * ourai_bridge.MAX_EVIDENCE_BYTES
    def respond(_request):
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(payload).encode("utf-8")))
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result
    assert "secret" not in str(result)


def test_compressed_loopback_response_is_rejected_without_decompression():
    import gzip
    payload = sample()
    payload["secret"] = "x" * ourai_bridge.MAX_EVIDENCE_BYTES
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))
    assert len(compressed) < ourai_bridge.MAX_EVIDENCE_BYTES
    def respond(_request):
        return httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(compressed),
        )
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert "symbols" not in result



def test_evaluation_timestamp_cannot_precede_latest_prediction():
    """A synthetic upstream cannot report evidence evaluated before its forecast."""
    data = sample()
    data["evaluated_at_utc"] = "2026-10-20T13:59:59Z"
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert "symbols" not in result
    assert "latest_by_symbol" not in result
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False


def test_evaluation_timestamp_may_equal_latest_prediction():
    data = sample()
    data["evaluated_at_utc"] = "2026-10-20T14:00:20Z"
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "available"
    assert result["as_of"] == data["evaluated_at_utc"]


@pytest.mark.parametrize(
    ("evaluated_at", "expected_status"),
    [
        ("2026-10-20T14:14:59Z", "unavailable"),
        ("2026-10-20T14:15:00Z", "available"),
        ("2026-10-20T15:15:00+01:00", "available"),
    ],
)
def test_resolved_latest_forecast_cannot_precede_its_target_due_at(
    evaluated_at, expected_status,
):
    """Synthetic forward evidence must not resolve a future 15m target."""
    data = sample()
    data["latest_by_symbol"]["NVDA"]["resolved"] = True
    data["evaluated_at_utc"] = evaluated_at
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == expected_status
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    if expected_status == "unavailable":
        assert result["unavailable_reason"] == "invalid_upstream_evidence"
        assert "symbols" not in result and "latest_by_symbol" not in result



@pytest.mark.parametrize("location", ["global", "symbol", "latest"])
def test_huge_json_numeric_metric_fails_closed_without_500(location):
    """A bounded response can still contain an integer too large for float."""
    data = sample()
    if location == "global":
        data["champion_mae_bps"] = 10 ** 400
    elif location == "symbol":
        data["symbols"]["NVDA"]["champion_mae_bps"] = 10 ** 400
    else:
        data["latest_by_symbol"]["NVDA"]["expected_magnitude_bps"] = 10 ** 400

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result


def test_deeply_nested_but_small_json_fails_closed_without_500():
    """A 40 KiB JSON response can exceed parser nesting limits."""
    depth = 20_000
    content = b"[" * depth + b"0" + b"]" * depth
    assert len(content) < ourai_bridge.MAX_EVIDENCE_BYTES

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, stream=httpx.ByteStream(content))
        ),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "gzip, identity"])
def test_even_small_encoded_evidence_is_rejected_before_decompression(encoding):
    """The producer sends plain JSON; no compressed listener may bypass limits."""
    payload = sample()
    payload["secret"] = "must-not-leak"
    seen = []

    def respond(request):
        seen.append(request.headers["Accept-Encoding"])
        return httpx.Response(
            200,
            headers={"Content-Encoding": encoding},
            stream=httpx.ByteStream(json.dumps(payload).encode("utf-8")),
        )

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert seen == ["identity"]
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result
    assert "secret" not in str(result)


def test_plain_json_evidence_remains_accepted_with_identity_encoding():
    payload = sample()
    def respond(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200, headers={"Content-Encoding": "identity"},
            stream=httpx.ByteStream(json.dumps(payload).encode("utf-8")),
        )

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert result["status"] == "available"
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False


@pytest.mark.parametrize(
    ("field", "timestamp"),
    [
        ("target_due_at", "2026-10-20T14:14:00Z"),
        ("target_due_at", "2026-10-20T14:16:00Z"),
        ("sample_timestamp", "2026-10-20T13:59:00Z"),
    ],
)
def test_latest_magnitude_forecast_requires_exact_15m_horizon(field, timestamp):
    """Even causally ordered evidence must match the frozen 15m contract."""
    data = sample()
    data["latest_by_symbol"]["NVDA"][field] = timestamp
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert "latest_by_symbol" not in result
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False


def test_latest_horizon_is_compared_as_elapsed_time_across_offsets():
    """Equivalent offset-aware timestamps must preserve a valid 15m horizon."""
    data = sample()
    data["latest_by_symbol"]["NVDA"]["sample_timestamp"] = "2026-10-20T16:00:00+02:00"
    data["latest_by_symbol"]["NVDA"]["target_due_at"] = "2026-10-20T10:15:00-04:00"
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "available"
    assert result["horizon_minutes"] == 15
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False


@pytest.mark.parametrize(
    ("needle", "duplicate"),
    [
        ('"journal_valid": true', '"journal_valid": false, "journal_valid": true'),
        ('"predictions": 2', '"predictions": 99, "predictions": 2'),
        ('"expected_magnitude_bps": 12.0',
         '"expected_magnitude_bps": -1, "expected_magnitude_bps": 12.0'),
    ],
)
def test_duplicate_json_keys_fail_closed_at_any_evidence_depth(needle, duplicate):
    """A last-wins JSON parser could hide invalid journal or forecast fields."""
    content = json.dumps(sample())
    assert content.count(needle) == 1
    content = content.replace(needle, duplicate, 1)

    def respond(_request):
        return httpx.Response(
            200, stream=httpx.ByteStream(content.encode("utf-8")),
        )

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result
