import httpx
import inspect
import pytest

from app.services.trading212_demo import Trading212DemoBroker


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"
        self.headers = {"content-type": "application/json"}
        self.text = ""

    def json(self):
        return self._payload


def test_demo_connector_is_fixed_to_demo_basic_auth_and_caches_reads(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/equity/account/summary"):
            return FakeResponse({"currency": "EUR", "cash": {"availableToTrade": 1000}})
        if url.endswith("/equity/positions"):
            return FakeResponse([{"ticker": "AAPL_US_EQ", "quantity": 2}])
        return FakeResponse({"items": [{"id": len(calls)}]})

    monkeypatch.setattr(httpx, "request", fake_request)
    broker = Trading212DemoBroker(cache_seconds=30)

    first = broker.connect("user-1", "demo-key", "demo-secret")
    second = broker.overview("user-1")

    assert Trading212DemoBroker.BASE_URL == "https://demo.trading212.com/api/v0"
    assert all(method == "GET" for method, _, _ in calls)
    assert all(url.startswith(Trading212DemoBroker.BASE_URL) for _, url, _ in calls)
    assert isinstance(calls[0][2]["auth"], httpx.BasicAuth)
    assert len(calls) == 6
    assert first["positions"][0]["ticker"] == "AAPL_US_EQ"
    assert second["freshness"]["cache_status"] == "cached"
    assert broker.status("user-1")["credentials_persisted"] is False
    assert broker.status("user-1")["live_trading_supported"] is False


def test_demo_connector_preserves_account_when_optional_feed_fails(monkeypatch):
    def fake_request(method, url, **kwargs):
        if url.endswith("/equity/account/summary"):
            return FakeResponse({"currency": "EUR"})
        if url.endswith("/equity/history/transactions"):
            return FakeResponse({"title": "Temporarily unavailable"}, 503)
        return FakeResponse([])

    monkeypatch.setattr(httpx, "request", fake_request)
    result = Trading212DemoBroker().connect("user-1", "key", "secret")

    assert result["account"]["currency"] == "EUR"
    assert result["partial_failure"] is True
    assert result["transactions"] == []
    assert "503" in result["errors"]["transactions"]


def test_demo_connector_marks_optional_permission_failures(monkeypatch):
    def fake_request(method, url, **kwargs):
        if url.endswith("/equity/account/summary"):
            return FakeResponse({"currency": "EUR"})
        if url.endswith("/equity/orders"):
            return FakeResponse({}, 403)
        return FakeResponse([])

    monkeypatch.setattr(httpx, "request", fake_request)
    result = Trading212DemoBroker().connect("user-1", "key", "secret")

    assert result["partial_failure"] is True
    assert result["permission_limited_sections"] == ["pending_orders"]


def test_failed_account_validation_forgets_credentials(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: FakeResponse({"title": "Unauthorized"}, 401),
    )
    broker = Trading212DemoBroker()

    try:
        broker.connect("user-1", "bad-key", "bad-secret")
        assert False, "invalid credentials must fail closed"
    except ValueError as exc:
        assert "401" in str(exc)

    assert broker.status("user-1")["connected"] is False


def test_demo_connector_rejects_any_non_allowlisted_endpoint():
    broker = Trading212DemoBroker()
    broker._credentials["user-1"] = ("key", "secret")

    with pytest.raises(ValueError, match="read endpoint"):
        broker._read_request("user-1", "place_order")
    with pytest.raises(ValueError, match="order type"):
        broker._submit_order_request("user-1", "unknown", {})
    with pytest.raises(ValueError, match="numeric"):
        broker._cancel_order_request("user-1", "../../account")


def test_demo_connector_source_contains_no_live_host_or_autonomous_method():
    source = inspect.getsource(Trading212DemoBroker)

    assert "live.trading212.com" not in source
    assert 'httpx.request(\n            "GET"' in source
    assert 'httpx.request(\n            "POST"' in source
    assert 'httpx.request(\n            "DELETE"' in source
    assert "autonomous" not in {
        name.lower() for name in dir(Trading212DemoBroker)
    }


def test_demo_submission_is_independently_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TRADING212_DEMO_ORDER_SUBMISSION_ENABLED", raising=False)
    broker = Trading212DemoBroker()
    broker._credentials["user-1"] = ("key", "secret")

    assert broker.status("user-1")["order_submission_enabled"] is False
    assert broker.status("user-1")["manual_confirmation_required"] is True
    assert broker.status("user-1")["autonomous_orders_supported"] is False
    with pytest.raises(ValueError, match="disabled"):
        broker.place_order(
            "user-1",
            ticker="AAPL_US_EQ",
            side="buy",
            quantity=1,
            order_type="market",
        )


@pytest.mark.parametrize(
    ("order_type", "side", "prices", "expected"),
    [
        ("market", "buy", {}, {
            "ticker": "AAPL_US_EQ", "quantity": 2.0, "extendedHours": False,
        }),
        ("limit", "sell", {"limit_price": 150}, {
            "ticker": "AAPL_US_EQ", "quantity": -2.0,
            "timeValidity": "DAY", "limitPrice": 150.0,
        }),
        ("stop", "sell", {"stop_price": 140}, {
            "ticker": "AAPL_US_EQ", "quantity": -2.0,
            "timeValidity": "DAY", "stopPrice": 140.0,
        }),
        ("stop_limit", "buy", {"limit_price": 150, "stop_price": 145}, {
            "ticker": "AAPL_US_EQ", "quantity": 2.0,
            "timeValidity": "DAY", "limitPrice": 150.0, "stopPrice": 145.0,
        }),
    ],
)
def test_demo_order_payloads_use_fixed_official_routes(
    monkeypatch, order_type, side, prices, expected
):
    monkeypatch.setenv("TRADING212_DEMO_ORDER_SUBMISSION_ENABLED", "true")
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse({"id": 1234})

    monkeypatch.setattr(httpx, "request", fake_request)
    broker = Trading212DemoBroker()
    broker._credentials["user-1"] = ("key", "secret")

    result = broker.place_order(
        "user-1",
        ticker="AAPL_US_EQ",
        side=side,
        quantity=2,
        order_type=order_type,
        **prices,
    )

    assert result["id"] == 1234
    assert calls == [(
        "POST",
        f"https://demo.trading212.com/api/v0/equity/orders/{order_type}",
        calls[0][2],
    )]
    assert calls[0][2]["json"] == expected


def test_demo_instrument_search_is_cached_and_ranked(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        return FakeResponse([
            {
                "ticker": "AAPL_US_EQ", "name": "Apple Inc.",
                "isin": "US0378331005", "currencyCode": "USD",
            },
            {"ticker": "APLE_US_EQ", "name": "Apple Hospitality"},
        ])

    monkeypatch.setattr(httpx, "request", fake_request)
    broker = Trading212DemoBroker()
    broker._credentials["user-1"] = ("key", "secret")

    first = broker.instruments("user-1", "AAPL")
    second = broker.instruments("user-1", "Apple")

    assert first[0]["ticker"] == "AAPL_US_EQ"
    assert [item["ticker"] for item in second] == ["AAPL_US_EQ", "APLE_US_EQ"]
    assert len(calls) == 1


def test_demo_instrument_universe_preserves_broker_tickers_and_reports_gaps(
    monkeypatch,
):
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *_args, **_kwargs: FakeResponse([
            {
                "ticker": "AAPL_US_EQ",
                "name": "Apple Inc.",
                "isin": "US0378331005",
                "currencyCode": "USD",
                "type": "STOCK",
            },
            {
                "ticker": "VUSA_GB_EQ",
                "name": "Vanguard S&P 500",
                "currencyCode": "GBP",
                "type": "ETF",
            },
            {
                "ticker": "UNKNOWN_XX_EQ",
                "name": "Unsupported exchange",
            },
            {
                "ticker": "AAPL_US_EQ",
                "name": "Duplicate",
            },
        ]),
    )
    broker = Trading212DemoBroker()
    broker._credentials["user-1"] = ("key", "secret")

    universe = broker.instrument_universe("user-1")

    assert [item["market_symbol"] for item in universe["items"]] == [
        "AAPL",
        "VUSA.L",
    ]
    assert universe["items"][0]["broker_ticker"] == "AAPL_US_EQ"
    assert universe["provider_count"] == 4
    assert universe["mapped_count"] == 2
    assert universe["unsupported_count"] == 1
    assert universe["duplicate_market_symbols"] == 1
    assert broker.instrument_market_symbol("BRK_B_US_EQ") == "BRK_B"


def test_demo_cancel_is_fixed_to_numeric_order_id(monkeypatch):
    monkeypatch.setenv("TRADING212_DEMO_ORDER_SUBMISSION_ENABLED", "true")
    calls = []
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kwargs: (
            calls.append((method, url)) or FakeResponse({})
        ),
    )
    broker = Trading212DemoBroker()
    broker._credentials["user-1"] = ("key", "secret")

    broker.cancel_order("user-1", "12345")

    assert calls == [(
        "DELETE",
        "https://demo.trading212.com/api/v0/equity/orders/12345",
    )]
