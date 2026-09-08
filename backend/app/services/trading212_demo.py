import copy
import os
import time
from datetime import datetime, timezone
from threading import Lock

import httpx


class Trading212DemoAPIError(ValueError):
    def __init__(self, status_code, detail):
        self.status_code = int(status_code)
        super().__init__(
            f"Trading 212 Demo API error ({self.status_code}): "
            f"{detail or 'request rejected'}"
        )


class Trading212DemoBroker:
    """Trading 212 Demo adapter with tightly allow-listed manual orders.

    The host and every method/path pair are deliberately fixed. The adapter
    cannot reach the Live environment and exposes no autonomous-order method.
    """

    BASE_URL = "https://demo.trading212.com/api/v0"
    ENDPOINTS = {
        "account": "/equity/account/summary",
        "positions": "/equity/positions",
        "pending_orders": "/equity/orders",
        "historical_orders": "/equity/history/orders",
        "transactions": "/equity/history/transactions",
        "dividends": "/equity/history/dividends",
        "instruments": "/equity/metadata/instruments",
    }
    ORDER_ENDPOINTS = {
        "market": "/equity/orders/market",
        "limit": "/equity/orders/limit",
        "stop": "/equity/orders/stop",
        "stop_limit": "/equity/orders/stop_limit",
    }
    YAHOO_EXCHANGE_SUFFIXES = {
        "US_EQ": "",
        "GB_EQ": ".L",
        "DE_EQ": ".DE",
        "NL_EQ": ".AS",
        "FR_EQ": ".PA",
        "ES_EQ": ".MC",
        "IT_EQ": ".MI",
        "CH_EQ": ".SW",
        "SE_EQ": ".ST",
        "NO_EQ": ".OL",
        "DK_EQ": ".CO",
        "FI_EQ": ".HE",
        "BE_EQ": ".BR",
        "AT_EQ": ".VI",
        "PT_EQ": ".LS",
        "IE_EQ": ".IR",
        "PL_EQ": ".WA",
        "CZ_EQ": ".PR",
        "CA_EQ": ".TO",
        "AU_EQ": ".AX",
        "JP_EQ": ".T",
        "HK_EQ": ".HK",
    }

    def __init__(self, cache_seconds=10):
        self.cache_seconds = max(1, int(cache_seconds))
        self._credentials = {}
        self._snapshots = {}
        self._instrument_snapshots = {}
        self._lock = Lock()

    def _credentials_for(self, user_id):
        credentials = self._credentials.get(user_id)
        if credentials is None:
            raise ValueError("Trading 212 Demo is not connected")
        return credentials

    @staticmethod
    def _response_payload(response):
        if response.status_code >= 400:
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                payload = response.json()
                detail = (
                    payload.get("clarification")
                    or payload.get("detail")
                    or payload.get("title")
                    or payload.get("message")
                    or payload.get("code")
                    if isinstance(payload, dict)
                    else str(payload)
                )
            else:
                detail = response.text.strip()
            raise Trading212DemoAPIError(response.status_code, detail)
        return response.json() if response.content else {}

    def _read_request(self, user_id, endpoint, params=None):
        if endpoint not in self.ENDPOINTS:
            raise ValueError("Unsupported Trading 212 Demo read endpoint")
        credentials = self._credentials_for(user_id)
        response = httpx.request(
            "GET",
            f"{self.BASE_URL}{self.ENDPOINTS[endpoint]}",
            auth=httpx.BasicAuth(credentials[0], credentials[1]),
            headers={"Accept": "application/json"},
            params=params,
            timeout=20,
        )
        return self._response_payload(response)

    def _submit_order_request(self, user_id, order_type, payload):
        if order_type not in self.ORDER_ENDPOINTS:
            raise ValueError("Unsupported Trading 212 Demo order type")
        credentials = self._credentials_for(user_id)
        response = httpx.request(
            "POST",
            f"{self.BASE_URL}{self.ORDER_ENDPOINTS[order_type]}",
            auth=httpx.BasicAuth(credentials[0], credentials[1]),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        return self._response_payload(response)

    def _cancel_order_request(self, user_id, order_id):
        order_id = str(order_id).strip()
        if not order_id.isdigit():
            raise ValueError("Trading 212 Demo order ID must be numeric")
        credentials = self._credentials_for(user_id)
        response = httpx.request(
            "DELETE",
            f"{self.BASE_URL}/equity/orders/{order_id}",
            auth=httpx.BasicAuth(credentials[0], credentials[1]),
            headers={"Accept": "application/json"},
            timeout=20,
        )
        return self._response_payload(response)

    @staticmethod
    def _items(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return payload["items"]
        return payload

    def connect(self, user_id, api_key, api_secret):
        api_key, api_secret = str(api_key).strip(), str(api_secret).strip()
        if not api_key or not api_secret:
            raise ValueError("Both Trading 212 Demo credentials are required")
        with self._lock:
            self._credentials[user_id] = (api_key, api_secret)
            self._snapshots.pop(user_id, None)
        try:
            return self.overview(user_id, force=True)
        except Exception:
            self.disconnect(user_id)
            raise

    def disconnect(self, user_id):
        with self._lock:
            self._credentials.pop(user_id, None)
            self._snapshots.pop(user_id, None)
            self._instrument_snapshots.pop(user_id, None)

    def status(self, user_id):
        submission_enabled = (
            os.getenv("TRADING212_DEMO_ORDER_SUBMISSION_ENABLED", "false").lower()
            == "true"
        )
        return {
            "connected": user_id in self._credentials,
            "environment": "demo",
            "demo_only": True,
            "read_only": not submission_enabled,
            "order_submission_enabled": submission_enabled,
            "manual_confirmation_required": True,
            "autonomous_orders_supported": False,
            "credentials_persisted": False,
            "live_trading_supported": False,
        }

    def _instrument_payload(self, user_id, force=False):
        self._credentials_for(user_id)
        cached = self._instrument_snapshots.get(user_id)
        now = time.monotonic()
        if force or not cached or now - cached["cached_at"] >= 600:
            payload = self._items(self._read_request(user_id, "instruments"))
            payload = payload if isinstance(payload, list) else []
            with self._lock:
                self._instrument_snapshots[user_id] = {
                    "cached_at": now,
                    "payload": copy.deepcopy(payload),
                }
        else:
            payload = copy.deepcopy(cached["payload"])
        return payload

    @classmethod
    def instrument_market_symbol(cls, instrument):
        ticker = (
            str(instrument.get("ticker") or "")
            if isinstance(instrument, dict)
            else str(instrument or "")
        ).strip().upper()
        for suffix, exchange_suffix in cls.YAHOO_EXCHANGE_SUFFIXES.items():
            marker = f"_{suffix}"
            if ticker.endswith(marker):
                symbol = ticker[:-len(marker)]
                return f"{symbol}{exchange_suffix}" if symbol else None
        return None

    def instrument_universe(self, user_id, force=False):
        """Return Trading 212 instruments that can be mapped for market research.

        The broker ticker remains the source of truth. ``market_symbol`` is only
        a quote/research alias for the independent market-data provider.
        """
        payload = self._instrument_payload(user_id, force=force)
        items, unsupported, duplicates = [], 0, 0
        seen_market_symbols = set()
        for raw in payload:
            if not isinstance(raw, dict):
                unsupported += 1
                continue
            broker_ticker = str(raw.get("ticker") or "").strip().upper()
            market_symbol = self.instrument_market_symbol(raw)
            if not broker_ticker or not market_symbol:
                unsupported += 1
                continue
            if market_symbol in seen_market_symbols:
                duplicates += 1
                continue
            seen_market_symbols.add(market_symbol)
            items.append({
                "symbol": market_symbol,
                "market_symbol": market_symbol,
                "broker_ticker": broker_ticker,
                "name": raw.get("name") or raw.get("shortName") or market_symbol,
                "short_name": raw.get("shortName") or raw.get("name") or market_symbol,
                "isin": raw.get("isin"),
                "currency": raw.get("currencyCode") or raw.get("currency"),
                "instrument_type": raw.get("type") or "EQUITY",
            })
        return {
            "items": items,
            "provider_count": len(payload),
            "mapped_count": len(items),
            "unsupported_count": unsupported,
            "duplicate_market_symbols": duplicates,
            "cache_seconds": 600,
        }

    def instruments(self, user_id, query="", force=False):
        payload = self._instrument_payload(user_id, force=force)

        clean_query = str(query or "").strip().upper()
        if not clean_query:
            return []
        exact, prefix, contains = [], [], []
        for item in payload:
            if not isinstance(item, dict):
                continue
            fields = [
                str(item.get("ticker") or "").upper(),
                str(item.get("shortName") or "").upper(),
                str(item.get("name") or "").upper(),
                str(item.get("isin") or "").upper(),
            ]
            if clean_query in fields:
                exact.append(item)
            elif any(value.startswith(clean_query) for value in fields):
                prefix.append(item)
            elif any(clean_query in value for value in fields):
                contains.append(item)
        return (exact + prefix + contains)[:20]

    def place_order(
        self,
        user_id,
        *,
        ticker,
        side,
        quantity,
        order_type,
        limit_price=None,
        stop_price=None,
    ):
        if not self.status(user_id)["order_submission_enabled"]:
            raise ValueError(
                "Trading 212 Demo order submission is disabled by server policy"
            )
        ticker = str(ticker or "").strip().upper()
        side = str(side or "").strip().lower()
        order_type = str(order_type or "").strip().lower()
        quantity = float(quantity)
        if not ticker or side not in {"buy", "sell"} or quantity <= 0:
            raise ValueError("Invalid Trading 212 Demo order parameters")
        if order_type not in self.ORDER_ENDPOINTS:
            raise ValueError("Unsupported Trading 212 Demo order type")
        signed_quantity = quantity if side == "buy" else -quantity
        payload = {"ticker": ticker, "quantity": signed_quantity}
        if order_type == "market":
            payload["extendedHours"] = False
        else:
            payload["timeValidity"] = "DAY"
        if order_type in {"limit", "stop_limit"}:
            if limit_price is None or float(limit_price) <= 0:
                raise ValueError("Limit price must be greater than zero")
            payload["limitPrice"] = float(limit_price)
        if order_type in {"stop", "stop_limit"}:
            if stop_price is None or float(stop_price) <= 0:
                raise ValueError("Stop price must be greater than zero")
            payload["stopPrice"] = float(stop_price)
        result = self._submit_order_request(user_id, order_type, payload)
        with self._lock:
            self._snapshots.pop(user_id, None)
        return result

    def cancel_order(self, user_id, order_id):
        if not self.status(user_id)["order_submission_enabled"]:
            raise ValueError(
                "Trading 212 Demo order submission is disabled by server policy"
            )
        result = self._cancel_order_request(user_id, order_id)
        with self._lock:
            self._snapshots.pop(user_id, None)
        return result

    def overview(self, user_id, force=False):
        if user_id not in self._credentials:
            raise ValueError("Trading 212 Demo is not connected")
        cached = self._snapshots.get(user_id)
        now = time.monotonic()
        if not force and cached and now - cached["cached_at"] < self.cache_seconds:
            result = copy.deepcopy(cached["payload"])
            result["freshness"]["cache_status"] = "cached"
            return result

        account = self._read_request(user_id, "account")
        sections = {"account": account}
        errors = {}
        for endpoint in (
            "positions",
            "pending_orders",
            "historical_orders",
            "transactions",
            "dividends",
        ):
            try:
                params = {"limit": 20} if endpoint in {
                    "historical_orders", "transactions", "dividends",
                } else None
                sections[endpoint] = self._items(
                    self._read_request(user_id, endpoint, params=params)
                )
            except Exception as exc:
                sections[endpoint] = []
                errors[endpoint] = str(exc)

        payload = {
            **sections,
            "partial_failure": bool(errors),
            "errors": errors,
            "permission_limited_sections": [
                name for name, detail in errors.items() if "(403)" in detail
            ],
            "freshness": {
                "cache_status": "fresh",
                "cache_seconds": self.cache_seconds,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            "status": self.status(user_id),
        }
        with self._lock:
            self._snapshots[user_id] = {
                "cached_at": now,
                "payload": copy.deepcopy(payload),
            }
        return payload
