"""Fail-closed Orion backend integration tests for OurAI loopback evidence."""
from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone
import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
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



def test_slow_trickle_evidence_exceeds_total_deadline_and_fails_as_connection_outage(monkeypatch):
    """Even a peer that sends chunks inside each socket timeout cannot hang forever."""
    ticks = iter((0.0, ourai_bridge.MAX_RESPONSE_SECONDS + 0.1))
    monkeypatch.setattr(ourai_bridge, "monotonic", lambda: next(ticks))
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(sample()),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "upstream_connection_failure"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "champion_mae_bps" not in result


def test_prompt_loopback_evidence_remains_available_with_total_deadline(monkeypatch):
    ticks = iter((0.0, ourai_bridge.MAX_RESPONSE_SECONDS - 0.1, ourai_bridge.MAX_RESPONSE_SECONDS - 0.05))
    monkeypatch.setattr(ourai_bridge, "monotonic", lambda: next(ticks))
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(sample()),
    )
    assert result["status"] == "available"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False

def test_delayed_stream_completion_never_publishes_forward_evidence(monkeypatch):
    """A timely JSON chunk is insufficient when the response completes too late."""
    ticks = iter((0.0, 0.1, ourai_bridge.MAX_RESPONSE_SECONDS + 0.1))
    monkeypatch.setattr(ourai_bridge, "monotonic", lambda: next(ticks))
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(sample()),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "upstream_connection_failure"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "champion_mae_bps" not in result


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
    response = intelligence.ourai_forward_evidence(request, Response())
    assert response["status"] == "disabled"
    assert seen == [1]



@pytest.mark.parametrize("state", ["available", "unavailable", "disabled"])
def test_forward_evidence_http_responses_are_never_cached(monkeypatch, state):
    """An HTTP client must not reuse a stale verified or unavailable snapshot."""
    monkeypatch.setattr(
        ourai_bridge, "fetch_ourai_forward_evidence",
        lambda: {"status": state, "trading_enabled": False, "direction_available": False},
    )
    app = FastAPI()
    app.include_router(intelligence.router)

    @app.middleware("http")
    async def authenticated_local_user(request, call_next):
        request.state.user = {"id": "single-local-user"}
        return await call_next(request)

    with TestClient(app) as client:
        response = client.get("/intelligence/ourai/forward-evidence")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == state
    assert response.json()["trading_enabled"] is False


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
            intelligence.ourai_forward_evidence(request, Response())
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


@pytest.mark.parametrize("evaluated_at", [
    "2099-01-01T00:00:00Z",
    "2099-01-01T13:00:00+13:00",
])
def test_future_dated_evaluation_fails_closed(evaluated_at):
    """A report must not claim that future observations are verified."""
    data = sample()
    data["evaluated_at_utc"] = evaluated_at
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert "symbols" not in result and "latest_by_symbol" not in result
    assert "champion_mae_bps" not in result
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False


def test_current_evaluation_timestamp_is_accepted():
    """A current report with an overdue pending target remains valid."""
    data = sample()
    # The synthetic latest target was due on 2026-10-20, so a report
    # evaluated now must account for that overdue pending prediction.
    data["overdue_pending_count"] = 1
    data["symbols"]["NVDA"]["overdue_pending"] = 1
    data["evaluated_at_utc"] = datetime.now(timezone.utc).isoformat()
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "available"
    assert result["as_of"] == data["evaluated_at_utc"]
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False


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
            200, headers={"Content-Encoding": "identity", "Content-Type": "application/json; charset=utf-8"},
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


@pytest.mark.parametrize(
    ("evaluated_at", "overdue_count", "expected_status"),
    [
        ("2026-10-20T14:14:59Z", 0, "available"),
        ("2026-10-20T14:15:00Z", 0, "unavailable"),
        ("2026-10-20T14:15:00Z", 1, "available"),
    ],
)
def test_due_latest_pending_forecast_requires_overdue_count(
    evaluated_at, overdue_count, expected_status,
):
    """A verified snapshot cannot claim a due pending forecast is not overdue."""
    data = sample()
    data["evaluated_at_utc"] = evaluated_at
    data["overdue_pending_count"] = overdue_count
    data["symbols"]["NVDA"]["overdue_pending"] = overdue_count

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == expected_status
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    if expected_status == "unavailable":
        assert result["unavailable_reason"] == "invalid_upstream_evidence"
        assert "symbols" not in result and "latest_by_symbol" not in result


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


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
def test_loopback_redirect_never_contacts_non_loopback_destination(status_code):
    """A compromised local listener cannot redirect the read-only bridge."""
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(
            status_code,
            headers={"Location": "https://outside.invalid/forward-evidence"},
            stream=httpx.ByteStream(b""),
        )

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert requested == ["http://127.0.0.1:8765/v1/forward-evidence"]
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "upstream_http_failure"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result


@pytest.mark.parametrize("content_type", [
    None,
    "text/html",
    "application/problem+json",
    "application/octet-stream",
])
def test_loopback_evidence_rejects_unexpected_media_types(content_type):
    """Only the producer's JSON media type is trusted, even for valid JSON."""
    seen = []
    def respond(request):
        seen.append((request.headers["Accept"], request.headers["Accept-Encoding"]))
        headers = {} if content_type is None else {"Content-Type": content_type}
        return httpx.Response(
            200, headers=headers,
            stream=httpx.ByteStream(json.dumps(sample()).encode("utf-8")),
        )

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert seen == [("application/json", "identity")]
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert "symbols" not in result and "latest_by_symbol" not in result
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False


def test_loopback_evidence_accepts_producer_json_media_type_with_charset():
    def respond(request):
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(
            200, headers={"Content-Type": "application/json; charset=utf-8"},
            stream=httpx.ByteStream(json.dumps(sample()).encode("utf-8")),
        )

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert result["status"] == "available"
    assert result["trading_enabled"] is False
    assert result["direction_available"] is False


@pytest.mark.parametrize("status_code", [201, 202, 206])
def test_only_http_200_can_publish_verified_forward_evidence(status_code):
    """A valid-looking body with a non-200 2xx response is not verified evidence."""
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(sample(), status=status_code),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "upstream_http_failure"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result
    assert "champion_mae_bps" not in result

def test_real_loopback_http_recovery_after_transient_outage():
    """A 503 after verified data must clear evidence; recovery needs a fresh GET.

    The payload is synthetic and asserts transport/state behavior only, never
    actual forward performance or the existence of a settled forecast.
    """
    responses = [200, 503, 200]
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path))
            status = responses.pop(0)
            body = json.dumps(
                sample() if status == 200 else {"status": "temporarily_unavailable"}
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first = ourai_bridge.fetch_ourai_forward_evidence(enabled=True, port=server.server_port)
        outage = ourai_bridge.fetch_ourai_forward_evidence(enabled=True, port=server.server_port)
        recovered = ourai_bridge.fetch_ourai_forward_evidence(enabled=True, port=server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert requests == [("GET", ourai_bridge.ROUTE)] * 3
    assert responses == []
    assert first["status"] == "available"
    assert first["direction_available"] is False
    assert first["trading_enabled"] is False
    assert outage["status"] == "unavailable"
    assert outage["unavailable_reason"] == "upstream_http_failure"
    assert outage["direction_available"] is False
    assert outage["trading_enabled"] is False
    assert "symbols" not in outage and "latest_by_symbol" not in outage
    assert "champion_mae_bps" not in outage
    assert recovered["status"] == "available"
    assert recovered["prediction_count"] == first["prediction_count"]
    assert recovered["direction_available"] is False
    assert recovered["trading_enabled"] is False


def test_real_loopback_read_timeout_clears_evidence_then_recovers():
    """A slow verification is a data-availability outage, not model evidence.

    Exercise the real configured httpx read timeout over trusted loopback.
    The responses are synthetic; no model, journal or market data is used.
    """
    from threading import Event

    slow_started = Event()
    release_slow = Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if len(requests) == 2:
                # Mimic a full journal verification that takes longer than
                # Orion's 2s read timeout, without returning stale evidence.
                slow_started.set()
                release_slow.wait(timeout=10)
                return
            body = json.dumps(sample()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, port=server.server_port,
        )
        outage = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, port=server.server_port,
        )
        assert slow_started.is_set(), "slow response was not exercised"
        # Let the simulated verifier finish; recovery must make a fresh GET.
        release_slow.set()
        recovered = ourai_bridge.fetch_ourai_forward_evidence(
            enabled=True, port=server.server_port,
        )
    finally:
        release_slow.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert requests == [ourai_bridge.ROUTE] * 3
    assert first["status"] == "available"
    assert outage["status"] == "unavailable"
    assert outage["unavailable_reason"] == "upstream_connection_failure"
    assert outage["direction_available"] is False
    assert outage["trading_enabled"] is False
    assert "symbols" not in outage and "latest_by_symbol" not in outage
    assert "champion_mae_bps" not in outage
    assert recovered["status"] == "available"
    assert recovered["prediction_count"] == first["prediction_count"]
    assert recovered["direction_available"] is False
    assert recovered["trading_enabled"] is False


def test_partial_loopback_stream_reset_discards_evidence_then_recovers():
    """A reset after valid-looking bytes must never publish partial evidence.

    This is synthetic transport resilience, not forward model validation.
    """
    requests = []

    class ResetMidBody(httpx.SyncByteStream):
        def __iter__(self):
            yield json.dumps(sample()).encode("utf-8")[:64]
            raise httpx.ReadError("loopback connection reset mid-response")

    def broken(request):
        requests.append(("broken", str(request.url)))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=ResetMidBody(),
        )

    first = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(broken),
    )
    assert first["status"] == "unavailable"
    assert first["unavailable_reason"] == "upstream_connection_failure"
    assert first["mode"] == "RESEARCH_SHADOW_ONLY"
    assert first["direction_available"] is False
    assert first["trading_enabled"] is False
    assert "symbols" not in first and "latest_by_symbol" not in first
    assert "champion_mae_bps" not in first
    assert "connection reset" not in str(first)

    def recovered(request):
        requests.append(("recovered", str(request.url)))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(json.dumps(sample()).encode("utf-8")),
        )

    second = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(recovered),
    )
    assert requests == [
        ("broken", "http://127.0.0.1:8765/v1/forward-evidence"),
        ("recovered", "http://127.0.0.1:8765/v1/forward-evidence"),
    ]
    assert second["status"] == "available"
    assert second["prediction_count"] == sample()["prediction_count"]
    assert second["direction_available"] is False
    assert second["trading_enabled"] is False


@pytest.mark.parametrize("key", ("champion_mae_bps", "linear_mae_bps", "null_mae_bps"))
def test_global_mae_disagreement_with_resolved_symbol_evidence_fails_closed(key):
    """A verified label cannot mask a global MAE inconsistent with symbol rows."""
    data = sample()
    data[key] += 0.05
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "champion_mae_bps" not in result


def test_resolved_weighted_mae_allows_independent_three_decimal_rounding():
    """The actual producer rounds each symbol and global mean independently."""
    data = sample()
    data["prediction_count"] = 4
    data["resolution_count"] = 3
    data["pending_count"] = 1
    data["symbols"]["AAPL"] = {
        "predictions": 2, "resolved": 2, "pending": 0, "overdue_pending": 0,
        "champion_mae_bps": 8.701,
        "linear_mae_bps": 9.701,
        "null_mae_bps": 10.501,
    }
    data["latest_by_symbol"]["AAPL"] = {
        "symbol": "AAPL",
        "predicted_at": "2026-10-20T13:45:20Z",
        "sample_timestamp": "2026-10-20T13:45:00Z",
        "target_due_at": "2026-10-20T14:00:00Z",
        "expected_magnitude_bps": 12.0,
        "resolved": True,
    }
    data["champion_mae_bps"] = 8.701
    data["linear_mae_bps"] = 9.701
    data["null_mae_bps"] = 10.501

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "available"
    assert result["resolution_count"] == 3
    assert result["symbols"]["AAPL"]["resolved"] == 2
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False



@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
@pytest.mark.parametrize("nested", [False, True])
def test_nonfinite_json_anywhere_fails_closed(number, nested):
    """Even ignored fields cannot turn non-JSON or overflow into verified data.

    These are synthetic malformed responses, not actual forward evidence.
    Python's default json.loads accepts NaN/Infinity and 1e999 as infinity.
    """
    extra = '{"nested": ' + number + '}' if nested else number
    raw = json.dumps(sample())[:-1] + ', "untrusted_extra": ' + extra + '}'

    def respond(_request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(raw.encode("utf-8")),
        )

    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=httpx.MockTransport(respond),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result
    assert "champion_mae_bps" not in result

@pytest.mark.parametrize("invalid_horizon", [15.0, "15", True, None])
def test_forward_horizon_requires_exact_integer_schema_type(invalid_horizon):
    """JSON float 15.0 must not pass the integer-only frozen 15m contract."""
    data = sample()
    data["horizon_minutes"] = invalid_horizon
    result = ourai_bridge.fetch_ourai_forward_evidence(
        enabled=True, transport=transport_response(data),
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "invalid_upstream_evidence"
    assert result["direction_available"] is False
    assert result["trading_enabled"] is False
    assert "symbols" not in result and "latest_by_symbol" not in result
