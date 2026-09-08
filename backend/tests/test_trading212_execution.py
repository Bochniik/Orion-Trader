import pytest

from app.services.autonomy_store import AutonomyStore
from app.services.trading212_demo import Trading212DemoAPIError
from app.services.trading212_execution import Trading212DemoExecution


class FakeMarket:
    def get_quote(self, symbol):
        if symbol == "EURUSD=X":
            return {"price": 1.2}
        return {"price": 180}

    def get_profile(self, _symbol):
        return {"currency": "USD"}


class FakeBroker:
    BASE_URL = "https://demo.trading212.com/api/v0"

    def __init__(self):
        self.placed = []
        self.cancelled = []
        self.pending = []
        self.history = []
        self.positions = []

    def status(self, _user_id):
        return {
            "connected": True,
            "order_submission_enabled": True,
            "manual_confirmation_required": True,
        }

    def instruments(self, _user_id, query):
        if query == "AAPL_US_EQ":
            return [{
                "ticker": "AAPL_US_EQ",
                "name": "Apple Inc.",
                "isin": "US0378331005",
                "currencyCode": "USD",
            }]
        return []

    def overview(self, _user_id, force=False):
        assert force is True
        return {
            "account": {
                "currency": "EUR",
                "cash": {"availableToTrade": 5000, "total": 5000},
                "investments": {"currentValue": 0},
            },
            "positions": self.positions,
            "pending_orders": self.pending,
            "historical_orders": self.history,
        }

    def place_order(self, _user_id, **order):
        self.placed.append(order)
        return {"id": 777, "status": "NEW"}

    def cancel_order(self, _user_id, order_id):
        self.cancelled.append(order_id)
        return {}


def request(**updates):
    return {
        "ticker": "AAPL_US_EQ",
        "side": "buy",
        "order_type": "limit",
        "quantity": 2,
        "limit_price": 120,
        "stop_price": None,
        "thesis": "Breakout with defined risk",
        "invalidation_price": 110,
        **updates,
    }


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING212_DEMO_ORDER_SUBMISSION_ENABLED", "true")
    monkeypatch.setenv("TRADING212_DEMO_MAX_ORDER_VALUE", "1000")
    monkeypatch.setenv("TRADING212_DEMO_MAX_POSITION_PERCENT", "20")
    monkeypatch.setenv("TRADING212_DEMO_MAX_DAILY_ORDERS", "5")
    monkeypatch.setenv("TRADING212_DEMO_MAX_DAILY_NOTIONAL", "2500")
    return (
        Trading212DemoExecution(),
        FakeBroker(),
        AutonomyStore(tmp_path / "orion.db"),
        FakeMarket(),
    )


def test_review_resolves_exact_instrument_and_validates_account_currency(services):
    execution, broker, store, market = services

    review = execution.review(
        "user-1", request(), broker, store, market
    )

    assert review["status"] == "reviewed"
    assert review["market_symbol"] == "AAPL"
    assert review["validation"]["instrument"]["currency"] == "USD"
    assert review["validation"]["account"]["currency"] == "EUR"
    assert review["validation"]["estimated_notional"] == 200
    assert review["validation"]["fx"] == {
        "pair": "EURUSD=X",
        "rate": 1.2,
        "from_currency": "USD",
        "to_currency": "EUR",
    }
    assert all(gate["passed"] for gate in review["validation"]["gates"])


def test_duplicate_review_is_blocked(services):
    execution, broker, store, market = services
    execution.review("user-1", request(), broker, store, market)

    with pytest.raises(ValueError, match="No matching active order"):
        execution.review("user-1", request(), broker, store, market)


def test_review_fails_closed_on_order_value_and_exact_ticker(services):
    execution, broker, store, market = services

    with pytest.raises(ValueError, match="maximum"):
        execution.review(
            "user-1",
            request(quantity=20),
            broker,
            store,
            market,
        )
    with pytest.raises(ValueError, match="exact Trading 212 instrument"):
        execution.review(
            "user-1",
            request(ticker="NOT_A_BROKER_TICKER"),
            broker,
            store,
            market,
        )


def test_sell_requires_owned_quantity(services):
    execution, broker, store, market = services
    broker.positions = [{
        "ticker": "AAPL_US_EQ",
        "quantity": 1,
        "currentPrice": 120,
    }]

    with pytest.raises(ValueError, match="currently held"):
        execution.review(
            "user-1",
            request(side="sell", quantity=2),
            broker,
            store,
            market,
        )


def test_confirm_requires_explicit_click_and_revalidates(services):
    execution, broker, store, market = services
    review = execution.review("user-1", request(), broker, store, market)

    with pytest.raises(ValueError, match="Explicit"):
        execution.confirm(
            "user-1", review["review_id"], False,
            broker, store, market,
        )
    submitted = execution.confirm(
        "user-1", review["review_id"], True,
        broker, store, market,
    )

    assert submitted["status"] == "submitted"
    assert submitted["broker_order_id"] == "777"
    assert broker.placed == [{
        "ticker": "AAPL_US_EQ",
        "side": "buy",
        "quantity": 2.0,
        "order_type": "limit",
        "limit_price": 120.0,
        "stop_price": None,
    }]


def test_atomic_transition_prevents_double_confirmation(services):
    execution, broker, store, market = services
    review = execution.review("user-1", request(), broker, store, market)

    store.transition_trading212_order(
        review["review_id"], ("reviewed",), "submitting"
    )

    with pytest.raises(ValueError, match="state changed"):
        store.transition_trading212_order(
            review["review_id"], ("reviewed",), "submitting"
        )


def test_unknown_submission_outcome_is_not_retried(services):
    execution, broker, store, market = services
    review = execution.review("user-1", request(), broker, store, market)

    def fail(*_args, **_kwargs):
        raise ValueError("connection reset")

    broker.place_order = fail
    with pytest.raises(ValueError, match="Use Reconcile"):
        execution.confirm(
            "user-1", review["review_id"], True,
            broker, store, market,
        )

    assert store.get_trading212_order(review["review_id"])[
        "status"
    ] == "submission_unknown"


def test_broker_4xx_is_recorded_as_known_rejection(services):
    execution, broker, store, market = services
    review = execution.review("user-1", request(), broker, store, market)

    def reject(*_args, **_kwargs):
        raise Trading212DemoAPIError(403, "orders permission required")

    broker.place_order = reject
    with pytest.raises(ValueError, match="rejected the order"):
        execution.confirm(
            "user-1", review["review_id"], True,
            broker, store, market,
        )

    rejected = store.get_trading212_order(review["review_id"])
    assert rejected["status"] == "submission_rejected"
    assert rejected["broker"]["status_code"] == 403


def test_reconciliation_uniquely_recovers_unknown_submission(services):
    execution, broker, store, market = services
    review = execution.review("user-1", request(), broker, store, market)
    store.transition_trading212_order(
        review["review_id"], ("reviewed",), "submitting"
    )
    unknown = store.update_trading212_order(
        review["review_id"], "submission_unknown"
    )
    created = unknown["updated_at"].replace(" ", "T") + "Z"
    broker.history = [{
        "id": 888,
        "ticker": "AAPL_US_EQ",
        "quantity": 2,
        "status": "FILLED",
        "averagePrice": 120,
        "filledValue": 200,
        "dateCreated": created,
        "dateExecuted": created,
    }]

    result = execution.reconcile("user-1", broker, store)

    assert result["updated"] == 1
    assert result["journal_synced"] == 1
    restored = store.get_trading212_order(review["review_id"])
    assert restored["broker_order_id"] == "888"
    assert restored["status"] == "filled"


def test_reconciliation_is_idempotent_and_syncs_filled_trade(services):
    execution, broker, store, market = services
    review = execution.review("user-1", request(), broker, store, market)
    execution.confirm(
        "user-1", review["review_id"], True,
        broker, store, market,
    )
    broker.history = [{
        "id": 777,
        "status": "FILLED",
        "filledQuantity": 2,
        "averagePrice": 119,
        "filledValue": 198.33,
        "dateExecuted": "2026-07-30T12:00:00Z",
    }]

    first = execution.reconcile("user-1", broker, store)
    second = execution.reconcile("user-1", broker, store)
    trades = store.list_external_trades("trading212_demo")

    assert first["updated"] == 1
    assert first["journal_synced"] == 1
    assert second["journal_synced"] == 0
    assert len(trades) == 1
    assert trades[0]["broker_order_id"] == "777"
    assert trades[0]["price_currency"] == "USD"
    assert trades[0]["journal"]["thesis"] == "Breakout with defined risk"


def test_cancel_requires_second_confirmation(services):
    execution, broker, store, market = services
    review = execution.review("user-1", request(), broker, store, market)
    execution.confirm(
        "user-1", review["review_id"], True,
        broker, store, market,
    )

    with pytest.raises(ValueError, match="cancellation confirmation"):
        execution.cancel(
            "user-1", review["review_id"], False, broker, store
        )
    cancelled = execution.cancel(
        "user-1", review["review_id"], True, broker, store
    )

    assert cancelled["status"] == "cancellation_requested"
    assert broker.cancelled == ["777"]


def test_execution_class_exposes_no_autonomous_submission_method():
    assert not any(
        "autonom" in name.lower()
        for name in dir(Trading212DemoExecution)
    )
