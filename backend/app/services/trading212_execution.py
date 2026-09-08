import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from app.services.trading212_demo import Trading212DemoAPIError


class Trading212DemoExecution:
    """Deterministic review/confirm/reconcile layer for Demo orders only."""

    ACTIVE_STATUSES = {
        "submitted",
        "pending",
        "partially_filled",
    }
    TERMINAL_STATUSES = {"filled", "cancelled", "rejected", "expired"}

    @staticmethod
    def _number(name, default, lower, upper):
        try:
            value = float(os.getenv(name, default))
        except (TypeError, ValueError):
            value = float(default)
        return max(lower, min(value, upper))

    def limits(self):
        return {
            "max_order_value": self._number(
                "TRADING212_DEMO_MAX_ORDER_VALUE", 1000, 1, 1_000_000
            ),
            "max_position_percent": self._number(
                "TRADING212_DEMO_MAX_POSITION_PERCENT", 20, 0.1, 100
            ),
            "max_daily_orders": int(self._number(
                "TRADING212_DEMO_MAX_DAILY_ORDERS", 5, 1, 100
            )),
            "max_daily_notional": self._number(
                "TRADING212_DEMO_MAX_DAILY_NOTIONAL", 2500, 1, 10_000_000
            ),
            "review_ttl_seconds": int(self._number(
                "TRADING212_DEMO_REVIEW_TTL_SECONDS", 300, 30, 1800
            )),
        }

    @staticmethod
    def _instrument_market_symbol(instrument):
        from app.services.trading212_demo import Trading212DemoBroker

        return Trading212DemoBroker.instrument_market_symbol(instrument)

    @staticmethod
    def _account_notional(
        amount,
        instrument_currency,
        account_currency,
        market,
    ):
        instrument_currency = str(instrument_currency or "").upper()
        account_currency = str(account_currency or "").upper()
        if not instrument_currency:
            raise ValueError(
                "Trading 212 instrument currency is unavailable; order value "
                "cannot be validated safely"
            )
        if instrument_currency == account_currency:
            return float(amount), None
        pair = f"{account_currency}{instrument_currency}=X"
        quote = market.get_quote(pair)
        rate = float(quote.get("price") or 0)
        if rate <= 0:
            raise ValueError(
                f"A fresh {account_currency}/{instrument_currency} FX quote "
                "is required to validate this order"
            )
        return float(amount) / rate, {
            "pair": pair,
            "rate": rate,
            "from_currency": instrument_currency,
            "to_currency": account_currency,
        }

    @staticmethod
    def _cash(account):
        cash = account.get("cash") if isinstance(account.get("cash"), dict) else {}
        for value in (
            cash.get("availableToTrade"),
            cash.get("free"),
            cash.get("available"),
            account.get("availableCash"),
        ):
            if value not in (None, ""):
                return float(value)
        return 0.0

    @staticmethod
    def _equity(account):
        cash = account.get("cash") if isinstance(account.get("cash"), dict) else {}
        investments = (
            account.get("investments")
            if isinstance(account.get("investments"), dict)
            else {}
        )
        for value in (
            cash.get("total"),
            account.get("totalValue"),
            account.get("equity"),
        ):
            if value not in (None, ""):
                return float(value)
        return Trading212DemoExecution._cash(account) + float(
            investments.get("currentValue") or cash.get("invested") or 0
        )

    @staticmethod
    def _position_values(account, positions):
        investments = (
            account.get("investments")
            if isinstance(account.get("investments"), dict)
            else {}
        )
        invested_total = float(
            investments.get("currentValue")
            or (account.get("cash") or {}).get("invested")
            or 0
        )
        raw = {}
        direct = {}
        for position in positions or []:
            if not isinstance(position, dict):
                continue
            ticker = str(position.get("ticker") or "").upper()
            quantity = abs(float(position.get("quantity") or 0))
            current_price = float(
                position.get("currentPrice")
                or position.get("averagePricePaid")
                or 0
            )
            raw[ticker] = quantity * current_price
            direct_value = position.get("currentValue")
            if direct_value not in (None, ""):
                direct[ticker] = abs(float(direct_value))
        if not invested_total:
            return {**raw, **direct}
        direct_total = sum(direct.values())
        missing = {key: value for key, value in raw.items() if key not in direct}
        missing_total = sum(missing.values())
        remaining = max(0.0, invested_total - direct_total)
        estimated = {
            key: remaining * value / missing_total
            for key, value in missing.items()
        } if missing_total else {}
        return {**estimated, **direct}

    @staticmethod
    def _broker_id(payload):
        return str(
            (payload or {}).get("id")
            or (payload or {}).get("orderId")
            or ""
        )

    @staticmethod
    def _fingerprint(request):
        normalized = {
            key: request.get(key)
            for key in (
                "ticker", "side", "order_type", "quantity",
                "limit_price", "stop_price",
            )
        }
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _validate(
        self,
        user_id,
        request,
        broker,
        store,
        market,
        *,
        skip_duplicate=False,
    ):
        ticker = str(request.get("ticker") or "").strip().upper()
        side = str(request.get("side") or "").strip().lower()
        order_type = str(request.get("order_type") or "").strip().lower()
        quantity = float(request.get("quantity") or 0)
        limit_price = request.get("limit_price")
        stop_price = request.get("stop_price")
        limit_price = float(limit_price) if limit_price not in (None, "") else None
        stop_price = float(stop_price) if stop_price not in (None, "") else None
        if side not in {"buy", "sell"}:
            raise ValueError("Trading 212 side must be buy or sell")
        if order_type not in {"market", "limit", "stop", "stop_limit"}:
            raise ValueError(
                "Trading 212 order type must be market, limit, stop, or stop_limit"
            )
        if quantity <= 0:
            raise ValueError("Trading 212 quantity must be greater than zero")
        if order_type in {"limit", "stop_limit"} and not limit_price:
            raise ValueError("A positive limit price is required")
        if order_type in {"stop", "stop_limit"} and not stop_price:
            raise ValueError("A positive stop price is required")

        matches = broker.instruments(user_id, ticker)
        instrument = next(
            (
                item for item in matches
                if str(item.get("ticker") or "").upper() == ticker
            ),
            None,
        )
        if instrument is None:
            raise ValueError(
                "Select an exact Trading 212 instrument before reviewing the order"
            )
        quote_symbol = self._instrument_market_symbol(instrument)
        market_symbol = quote_symbol or ticker.split("_", 1)[0]
        if order_type == "market":
            if not quote_symbol:
                raise ValueError(
                    "A safe external quote mapping is unavailable for this "
                    "exchange; use a limit order"
                )
            quote = market.get_quote(quote_symbol)
            reference_price = float(quote.get("price") or 0)
            if reference_price <= 0:
                raise ValueError(
                    "A fresh reference quote is required for a market order; "
                    "use a limit order if this instrument cannot be quoted"
                )
        elif order_type == "limit":
            reference_price = limit_price
        elif order_type == "stop":
            reference_price = stop_price
        else:
            reference_price = max(limit_price, stop_price)

        overview = broker.overview(user_id, force=True)
        account = overview.get("account") or {}
        positions = overview.get("positions") or []
        equity = self._equity(account)
        cash = self._cash(account)
        account_currency = str(account.get("currency") or "EUR").upper()
        instrument_currency = (
            instrument.get("currencyCode")
            or instrument.get("currency")
        )
        if not instrument_currency:
            raise ValueError(
                "Trading 212 instrument metadata did not include a currency; "
                "order value cannot be validated safely"
            )
        estimated_notional, fx = self._account_notional(
            quantity * reference_price,
            instrument_currency,
            account_currency,
            market,
        )
        position_values = self._position_values(account, positions)
        current_position_value = position_values.get(ticker, 0.0)
        current_quantity = sum(
            float(position.get("quantity") or 0)
            for position in positions
            if str(position.get("ticker") or "").upper() == ticker
        )
        limits = self.limits()
        today = store.trading212_today_submission_summary()
        fingerprint = self._fingerprint({
            "ticker": ticker,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "limit_price": limit_price,
            "stop_price": stop_price,
        })

        gates = [
            {
                "name": "demo_environment",
                "passed": broker.BASE_URL == "https://demo.trading212.com/api/v0",
                "message": "Fixed Trading 212 Demo host",
            },
            {
                "name": "server_policy",
                "passed": broker.status(user_id)["order_submission_enabled"],
                "message": "Independent Demo submission flag",
            },
            {
                "name": "order_value",
                "passed": estimated_notional <= limits["max_order_value"],
                "message": (
                    f"Estimated value {estimated_notional:.2f} versus "
                    f"{limits['max_order_value']:.2f} maximum"
                ),
            },
            {
                "name": "daily_order_count",
                "passed": today["order_count"] < limits["max_daily_orders"],
                "message": (
                    f"{today['order_count']} of "
                    f"{limits['max_daily_orders']} submitted today"
                ),
            },
            {
                "name": "daily_notional",
                "passed": (
                    today["notional"] + estimated_notional
                    <= limits["max_daily_notional"]
                ),
                "message": (
                    f"Projected daily value "
                    f"{today['notional'] + estimated_notional:.2f} versus "
                    f"{limits['max_daily_notional']:.2f} maximum"
                ),
            },
        ]
        if side == "buy":
            gates.extend([
                {
                    "name": "available_cash",
                    "passed": estimated_notional <= cash,
                    "message": (
                        f"Estimated value {estimated_notional:.2f} versus "
                        f"{cash:.2f} available"
                    ),
                },
                {
                    "name": "position_concentration",
                    "passed": (
                        equity > 0
                        and current_position_value + estimated_notional
                        <= equity * limits["max_position_percent"] / 100
                    ),
                    "message": (
                        f"Projected position "
                        f"{current_position_value + estimated_notional:.2f} versus "
                        f"{limits['max_position_percent']:.2f}% account maximum"
                    ),
                },
            ])
        else:
            gates.append({
                "name": "owned_quantity",
                "passed": quantity <= current_quantity,
                "message": (
                    f"Sell {quantity:g} versus {current_quantity:g} currently held"
                ),
            })
        if not skip_duplicate:
            gates.append({
                "name": "duplicate_protection",
                "passed": not store.has_recent_trading212_duplicate(fingerprint),
                "message": "No matching active order was reviewed recently",
            })

        failures = [gate["message"] for gate in gates if not gate["passed"]]
        validation = {
            "allowed": not failures,
            "gates": gates,
            "failures": failures,
            "limits": limits,
            "account": {
                "currency": account_currency,
                "equity": round(equity, 2),
                "available_cash": round(cash, 2),
            },
            "instrument": {
                "ticker": ticker,
                "market_symbol": market_symbol,
                "name": instrument.get("name") or instrument.get("shortName"),
                "isin": instrument.get("isin"),
                "currency": str(instrument_currency).upper(),
            },
            "fx": fx,
            "reference_price": round(reference_price, 4),
            "estimated_notional": round(estimated_notional, 2),
        }
        return {
            "ticker": ticker,
            "market_symbol": market_symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "reference_price": reference_price,
            "estimated_notional": estimated_notional,
            "fingerprint": fingerprint,
            "validation": validation,
        }

    def review(self, user_id, request, broker, store, market):
        result = self._validate(user_id, request, broker, store, market)
        if not result["validation"]["allowed"]:
            raise ValueError(
                "Trading 212 Demo order blocked: "
                + "; ".join(result["validation"]["failures"])
            )
        now = datetime.now(timezone.utc)
        review = store.save_trading212_review({
            **result,
            "review_id": uuid.uuid4().hex,
            "status": "reviewed",
            "thesis": str(request.get("thesis") or "").strip(),
            "invalidation_price": request.get("invalidation_price"),
            "request": {
                "ticker": result["ticker"],
                "side": result["side"],
                "order_type": result["order_type"],
                "quantity": result["quantity"],
                "limit_price": result["limit_price"],
                "stop_price": result["stop_price"],
                "thesis": str(request.get("thesis") or "").strip(),
                "invalidation_price": request.get("invalidation_price"),
            },
            "expires_at": (
                now + timedelta(seconds=self.limits()["review_ttl_seconds"])
            ).isoformat(),
        })
        store.add_event(
            "trading212_order_reviewed",
            f"Trading 212 Demo {result['side'].upper()} review created for {result['ticker']}",
            {
                "review_id": review["review_id"],
                "estimated_notional": review["estimated_notional"],
            },
            "info",
        )
        return review

    def confirm(self, user_id, review_id, confirmed, broker, store, market):
        if confirmed is not True:
            raise ValueError("Explicit Trading 212 Demo order confirmation is required")
        order = store.get_trading212_order(review_id)
        if order["status"] != "reviewed":
            raise ValueError(
                f"Trading 212 Demo order cannot be confirmed from {order['status']} state"
            )
        if datetime.fromisoformat(order["expires_at"]) <= datetime.now(timezone.utc):
            store.update_trading212_order(review_id, "expired")
            raise ValueError("Trading 212 Demo order review expired; review it again")

        revalidated = self._validate(
            user_id,
            order["request"],
            broker,
            store,
            market,
            skip_duplicate=True,
        )
        if not revalidated["validation"]["allowed"]:
            store.update_trading212_order(
                review_id,
                "risk_rejected",
                validation=revalidated["validation"],
            )
            raise ValueError(
                "Trading 212 Demo order failed final validation: "
                + "; ".join(revalidated["validation"]["failures"])
            )
        store.transition_trading212_order(
            review_id,
            ("reviewed",),
            "submitting",
            validation=revalidated["validation"],
        )
        try:
            broker_order = broker.place_order(
                user_id,
                ticker=order["ticker"],
                side=order["side"],
                quantity=order["quantity"],
                order_type=order["order_type"],
                limit_price=order["limit_price"],
                stop_price=order["stop_price"],
            )
        except Trading212DemoAPIError as exc:
            if exc.status_code < 500:
                store.update_trading212_order(
                    review_id,
                    "submission_rejected",
                    broker={
                        "error": str(exc),
                        "status_code": exc.status_code,
                    },
                )
                store.add_event(
                    "trading212_submission_rejected",
                    "Trading 212 Demo rejected the submission before creating an order",
                    {
                        "review_id": review_id,
                        "status_code": exc.status_code,
                        "detail": str(exc),
                    },
                    "warning",
                )
                raise ValueError(
                    "Trading 212 Demo rejected the order and no broker order "
                    f"was recorded: {exc}"
                ) from exc
            store.update_trading212_order(
                review_id,
                "submission_unknown",
                broker={
                    "error": str(exc),
                    "status_code": exc.status_code,
                },
            )
            raise ValueError(
                "Trading 212 Demo returned a server error after submission. "
                "Use Reconcile and do not retry automatically."
            ) from exc
        except Exception as exc:
            store.update_trading212_order(
                review_id,
                "submission_unknown",
                broker={"error": str(exc)},
            )
            store.add_event(
                "trading212_submission_unknown",
                "Trading 212 Demo submission outcome is unknown; do not retry automatically",
                {"review_id": review_id, "detail": str(exc)},
                "warning",
            )
            raise ValueError(
                "Trading 212 Demo did not return a confirmed outcome. "
                "Use Reconcile before attempting another order."
            ) from exc
        broker_order_id = self._broker_id(broker_order)
        if not broker_order_id:
            store.update_trading212_order(
                review_id,
                "submission_unknown",
                broker=broker_order,
            )
            raise ValueError(
                "Trading 212 Demo accepted the request without an order ID. "
                "Use Reconcile and do not submit it again."
            )
        updated = store.update_trading212_order(
            review_id,
            "submitted",
            broker_order_id=broker_order_id,
            broker=broker_order,
        )
        store.add_event(
            "trading212_order_submitted",
            f"Manually confirmed Trading 212 Demo order {broker_order_id}",
            {"review_id": review_id, "broker_order_id": broker_order_id},
            "info",
        )
        return updated

    @staticmethod
    def _normalize_history_status(payload):
        raw = str(payload.get("status") or payload.get("result") or "").upper()
        if "CANCEL" in raw:
            return "cancelled"
        if "REJECT" in raw:
            return "rejected"
        if "EXPIRE" in raw:
            return "expired"
        if "FILL" in raw:
            return "filled"
        filled_quantity = abs(float(payload.get("filledQuantity") or 0))
        ordered_quantity = abs(float(
            payload.get("orderedQuantity")
            or payload.get("quantity")
            or filled_quantity
        ))
        if payload.get("dateExecuted") or filled_quantity:
            if ordered_quantity and filled_quantity < ordered_quantity:
                return "partially_filled"
            return "filled"
        return "resolved"

    @staticmethod
    def _parse_time(value):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @classmethod
    def _matches_unknown_submission(cls, order, payload):
        if str(payload.get("ticker") or "").upper() != order["ticker"]:
            return False
        payload_quantity = float(
            payload.get("orderedQuantity")
            or payload.get("quantity")
            or payload.get("filledQuantity")
            or 0
        )
        if abs(abs(payload_quantity) - float(order["quantity"])) > 1e-8:
            return False
        expected_sign = 1 if order["side"] == "buy" else -1
        if payload_quantity and (1 if payload_quantity > 0 else -1) != expected_sign:
            return False
        for field, order_field in (
            ("limitPrice", "limit_price"),
            ("stopPrice", "stop_price"),
        ):
            expected = order.get(order_field)
            actual = payload.get(field)
            if expected is not None and actual is not None:
                if abs(float(expected) - float(actual)) > 1e-8:
                    return False
        submitted_at = cls._parse_time(order.get("updated_at"))
        broker_time = cls._parse_time(
            payload.get("dateCreated")
            or payload.get("createdAt")
            or payload.get("dateModified")
        )
        return bool(
            submitted_at
            and broker_time
            and abs((broker_time - submitted_at).total_seconds()) <= 900
        )

    def reconcile(self, user_id, broker, store):
        overview = broker.overview(user_id, force=True)
        pending = {
            self._broker_id(item): item
            for item in overview.get("pending_orders", [])
            if self._broker_id(item)
        }
        historical = {
            self._broker_id(item): item
            for item in overview.get("historical_orders", [])
            if self._broker_id(item)
        }
        claimed_ids = {
            str(order.get("broker_order_id") or "")
            for order in store.list_trading212_orders(200)
            if order.get("broker_order_id")
        }
        changed, journaled = 0, 0
        for order in store.list_trading212_orders(200):
            broker_id = str(order.get("broker_order_id") or "")
            if (
                not broker_id
                and order["status"] == "submission_unknown"
            ):
                candidates = [
                    item
                    for item in [*pending.values(), *historical.values()]
                    if self._broker_id(item) not in claimed_ids
                    and self._matches_unknown_submission(order, item)
                ]
                if len(candidates) == 1:
                    broker_id = self._broker_id(candidates[0])
                    claimed_ids.add(broker_id)
            if not broker_id:
                continue
            if broker_id in pending:
                status = (
                    "cancellation_requested"
                    if order["status"] == "cancellation_requested"
                    else "pending"
                )
                payload = pending[broker_id]
            elif broker_id in historical:
                payload = historical[broker_id]
                status = self._normalize_history_status(payload)
            else:
                continue
            if status != order["status"] or payload != order["broker"]:
                order = store.update_trading212_order(
                    order["review_id"],
                    status,
                    broker_order_id=broker_id,
                    broker=payload,
                )
                changed += 1
            if status == "filled":
                journal_entry = store.sync_external_trade(order, payload)
                journaled += int(bool(journal_entry.get("created")))
        if changed or journaled:
            store.add_event(
                "trading212_orders_reconciled",
                f"Trading 212 Demo reconciliation updated {changed} orders",
                {"updated": changed, "journal_synced": journaled},
                "info",
            )
        return {
            "orders": store.list_trading212_orders(50),
            "updated": changed,
            "journal_synced": journaled,
            "overview": overview,
        }

    def cancel(self, user_id, review_id, confirmed, broker, store):
        if confirmed is not True:
            raise ValueError(
                "Explicit Trading 212 Demo cancellation confirmation is required"
            )
        order = store.get_trading212_order(review_id)
        if order["status"] not in self.ACTIVE_STATUSES:
            raise ValueError(
                f"Trading 212 Demo order cannot be cancelled from {order['status']} state"
            )
        if not order.get("broker_order_id"):
            raise ValueError("Trading 212 Demo order has no broker order ID")
        store.transition_trading212_order(
            review_id,
            tuple(self.ACTIVE_STATUSES),
            "cancellation_requested",
        )
        try:
            response = broker.cancel_order(user_id, order["broker_order_id"])
        except Exception as exc:
            try:
                store.transition_trading212_order(
                    review_id,
                    ("cancellation_requested",),
                    order["status"],
                    broker={**order["broker"], "cancel_error": str(exc)},
                )
            except ValueError:
                pass
            raise
        try:
            updated = store.transition_trading212_order(
                review_id,
                ("cancellation_requested",),
                "cancellation_requested",
                broker={**order["broker"], "cancel_response": response},
            )
        except ValueError:
            updated = store.get_trading212_order(review_id)
        store.add_event(
            "trading212_cancellation_requested",
            f"Trading 212 Demo cancellation requested for {order['broker_order_id']}",
            {"review_id": review_id, "broker_order_id": order["broker_order_id"]},
            "warning",
        )
        return updated
