import os
import secrets
import re
import logging
from datetime import datetime, time, timedelta, timezone
from threading import Lock
from zoneinfo import ZoneInfo
from app.services.market_catalogue_provider_bridge import (
    sync_market_catalogue_from_assets,
)


log = logging.getLogger("orion.market_catalogue")

import httpx


class AlpacaPaperBroker:
    BASE_URL = "https://paper-api.alpaca.markets"
    DATA_URL = "https://data.alpaca.markets"

    def __init__(self):
        self._credentials = {}
        self._lock = Lock()

    def _headers(self, user_id):
        credentials = self._credentials.get(user_id)
        if credentials is None:
            raise ValueError("Alpaca paper account is not connected")
        return {"APCA-API-KEY-ID": credentials[0], "APCA-API-SECRET-KEY": credentials[1], "Accept": "application/json"}

    def _request(self, user_id, method, path, payload=None, params=None, data_api=False):
        base_url = self.DATA_URL if data_api else self.BASE_URL
        response = httpx.request(method, f"{base_url}{path}", headers=self._headers(user_id), json=payload, params=params, timeout=20)
        if response.status_code >= 400:
            detail = response.json().get("message") if "application/json" in response.headers.get("content-type", "") else response.text
            raise ValueError(f"Alpaca paper API error ({response.status_code}): {detail}")
        return response.json() if response.content else {}

    def connect(self, user_id, key_id, secret_key):
        key_id, secret_key = str(key_id).strip(), str(secret_key).strip()
        if not key_id or not secret_key:
            raise ValueError("Both Alpaca paper credentials are required")
        with self._lock:
            self._credentials[user_id] = (key_id, secret_key)
        try:
            account = self._request(user_id, "GET", "/v2/account")
        except Exception:
            self.disconnect(user_id)
            raise
        return self._safe_account(account)

    def disconnect(self, user_id):
        with self._lock:
            self._credentials.pop(user_id, None)

    def status(self, user_id):
        return {"connected": user_id in self._credentials, "paper_only": True, "credentials_persisted": False, "order_submission_enabled": os.getenv("ALPACA_ORDER_SUBMISSION_ENABLED", "false").lower() == "true"}

    def stream_credentials(self, user_id):
        """Return ephemeral credentials to the backend stream service only."""
        credentials = self._credentials.get(user_id)
        if credentials is None:
            raise ValueError("Connect Alpaca Paper before starting market-data streams")
        return credentials

    def account(self, user_id):
        return self._safe_account(self._request(user_id, "GET", "/v2/account"))

    def positions(self, user_id):
        return self._request(user_id, "GET", "/v2/positions")

    def clock(self, user_id):
        return self._request(user_id, "GET", "/v2/clock")

    def calendar(self, user_id, start, end):
        return self._request(user_id, "GET", "/v2/calendar", params={"start": start, "end": end})

    @staticmethod
    def _supported_scanner_asset(asset):
        """Conservative US-equity universe filter for the research scanner.

        Alpaca's asset payload does not always expose a reliable security subtype.
        We therefore prefer explicit metadata/name clues and only use suffix rules
        that target obvious warrants/units/rights/preferreds. Legitimate share
        classes such as BRK.B / BF.B are deliberately preserved.
        """
        if not isinstance(asset, dict):
            return False

        if asset.get("status") != "active" or not asset.get("tradable"):
            return False

        symbol = str(asset.get("symbol") or "").strip().upper()
        name = str(asset.get("name") or "").strip().lower()

        if not symbol:
            return False

        # Strong name-based exclusions.
        junk_name_terms = (
            " warrant",
            "warrant ",
            " warrants",
            " unit",
            "units ",
            " right",
            "rights ",
            " preferred",
            "preferred ",
            "depositary shares",
            "depositary share",
        )
        padded_name = f" {name} "
        if any(term in padded_name for term in junk_name_terms):
            return False

        # Conservative symbol suffix exclusions. DO NOT exclude .A / .B classes.
        junk_suffixes = (
            ".WS", ".W", ".U", ".RT", ".R",
            "-WS", "-W", "-U", "-RT", "-R",
        )
        if symbol.endswith(junk_suffixes):
            return False

        # Common preferred-share forms observed in Alpaca/Yahoo universes:
        # ABR.PRF, AHL.PRD, AHT.PRA, etc.
        if re.search(r"\.PR[A-Z]?$", symbol):
            return False

        return True

    def assets(self, user_id):
        assets = self._request(
            user_id,
            "GET",
            "/v2/assets",
            params={
                "status": "active",
                "asset_class": "us_equity",
            },
        )

        supported_assets = [
            asset
            for asset in assets
            if self._supported_scanner_asset(asset)
        ]

        # Market Catalogue V2:
        # Persist the complete supported/tradable US-equity universe whenever
        # this already-existing Alpaca asset fetch runs.
        #
        # Catalogue persistence is deliberately non-fatal. A SQLite/catalogue
        # write problem must never break the scanner's ability to receive the
        # provider universe.
        try:
            sync_result = sync_market_catalogue_from_assets(
                supported_assets,
                source="alpaca_assets",
            )

            log.info(
                "Market catalogue synced from Alpaca assets: "
                "assets_seen=%s upserted=%s",
                sync_result.get("assets_seen"),
                sync_result.get("upserted"),
            )

        except Exception as exc:
            log.warning(
                "Market catalogue sync failed while Alpaca asset universe "
                "remains usable: %s",
                type(exc).__name__,
            )

        return supported_assets

    def market_candidates(self, user_id, limit=50):
        limit = max(10, min(int(limit), 100))
        errors = []
        groups = {"most_active": [], "gainers": [], "losers": []}
        try:
            payload = self._request(user_id, "GET", "/v1beta1/screener/stocks/most-actives", params={"top": limit, "by": "volume"}, data_api=True)
            groups["most_active"] = [row.get("symbol") for row in payload.get("most_actives", []) if row.get("symbol")]
        except Exception as exc:
            errors.append(f"Most-active screener: {exc}")
        try:
            payload = self._request(user_id, "GET", "/v1beta1/screener/stocks/movers", params={"top": limit}, data_api=True)
            groups["gainers"] = [row.get("symbol") for row in payload.get("gainers", []) if row.get("symbol")]
            groups["losers"] = [row.get("symbol") for row in payload.get("losers", []) if row.get("symbol")]
        except Exception as exc:
            errors.append(f"Mover screener: {exc}")
        # Discovery consumers still receive movers, but the most-active list is
        # exhausted first.  This prevents low-dollar-volume percentage movers
        # from displacing liquid names before downstream risk ranking occurs.
        symbols = [
            *groups["most_active"], *groups["gainers"], *groups["losers"]
        ]
        return list(dict.fromkeys(symbols))[:limit], errors

    def liquidity_candidates(self, user_id, limit=100):
        """Return the most-active universe without mover-list contamination.

        Share-volume leaders are only discovery inputs.  Orion subsequently
        ranks them by absolute dollar volume, spread, trade frequency and
        evidence coverage before any model sees them.
        """
        limit = max(10, min(int(limit), 100))
        try:
            payload = self._request(
                user_id,
                "GET",
                "/v1beta1/screener/stocks/most-actives",
                params={"top": limit, "by": "volume"},
                data_api=True,
            )
            symbols = [
                row.get("symbol")
                for row in payload.get("most_actives", [])
                if row.get("symbol")
            ]
            return list(dict.fromkeys(symbols))[:limit], []
        except Exception as exc:
            return [], [f"Most-active liquidity screener: {exc}"]

    def snapshots(self, user_id, symbols):
        clean = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if symbol))[:200]
        if not clean:
            return {}
        payload = self._request(user_id, "GET", "/v2/stocks/snapshots", params={"symbols": ",".join(clean), "feed": "iex"}, data_api=True)
        return payload.get("snapshots", payload) if isinstance(payload, dict) else {}

    def stock_bars(
        self,
        user_id,
        symbols,
        *,
        start,
        end,
        timeframe="1Min",
        feed="iex",
        adjustment="raw",
        limit=10000,
        max_pages=20,
    ):
        """Read-only Alpaca stock bars with bounded pagination.

        Returns provider-native bar dictionaries grouped by symbol. This method
        does not infer session type, freshness, or completeness; callers must
        apply their own session/freshness contracts.

        Supported feed values here are deliberately restricted to documented
        stock feeds used by Orion research.
        """
        clean = list(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in symbols
                if symbol
            )
        )[:50]

        if not clean:
            return {
                "bars": {},
                "next_page_token": None,
                "provider": "alpaca",
                "feed": feed,
                "timeframe": timeframe,
                "partial": False,
            }

        if feed not in {"iex", "sip", "boats", "otc"}:
            raise ValueError("Unsupported Alpaca stock-bar feed")

        if timeframe not in {"1Min", "5Min", "15Min", "30Min", "1Hour", "1Day"}:
            raise ValueError("Unsupported Alpaca stock-bar timeframe")

        try:
            limit = int(limit)
            max_pages = int(max_pages)
        except (TypeError, ValueError):
            raise ValueError("limit and max_pages must be integers") from None

        if not 1 <= limit <= 10000:
            raise ValueError("limit must be in [1, 10000]")

        if not 1 <= max_pages <= 100:
            raise ValueError("max_pages must be in [1, 100]")

        def iso(value):
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    raise ValueError("start/end datetimes must be timezone-aware")
                return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            raw = str(value or "").strip()
            if not raw:
                raise ValueError("start and end are required")
            return raw

        params = {
            "symbols": ",".join(clean),
            "timeframe": timeframe,
            "start": iso(start),
            "end": iso(end),
            "limit": limit,
            "adjustment": adjustment,
            "feed": feed,
            "sort": "asc",
        }

        grouped = {symbol: [] for symbol in clean}
        page_token = None
        pages = 0

        while True:
            request_params = dict(params)

            if page_token:
                request_params["page_token"] = page_token

            payload = self._request(
                user_id,
                "GET",
                "/v2/stocks/bars",
                params=request_params,
                data_api=True,
            )

            pages += 1

            bars = payload.get("bars", {}) if isinstance(payload, dict) else {}

            if isinstance(bars, dict):
                for symbol, rows in bars.items():
                    if symbol in grouped and isinstance(rows, list):
                        grouped[symbol].extend(
                            row for row in rows if isinstance(row, dict)
                        )

            page_token = (
                payload.get("next_page_token")
                if isinstance(payload, dict)
                else None
            )

            if not page_token or pages >= max_pages:
                break

        return {
            "bars": grouped,
            "next_page_token": page_token,
            "pages": pages,
            "provider": "alpaca",
            "feed": feed,
            "timeframe": timeframe,
            "start": params["start"],
            "end": params["end"],
            "partial": bool(page_token),
        }

    def premarket_bars(
        self,
        user_id,
        symbols,
        *,
        now=None,
        feed="iex",
        timeframe="1Min",
    ):
        """Fetch only today's US premarket window: 04:00 <= t < 09:30 ET.

        This is research data only. It does not claim consolidated-market
        completeness when the IEX feed is used.
        """
        now = now or datetime.now(timezone.utc)

        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        eastern = ZoneInfo("America/New_York")
        local_now = now.astimezone(eastern)

        premarket_start = datetime.combine(
            local_now.date(),
            time(4, 0),
            tzinfo=eastern,
        )

        regular_open = datetime.combine(
            local_now.date(),
            time(9, 30),
            tzinfo=eastern,
        )

        end = min(local_now, regular_open)

        if end <= premarket_start:
            return {
                "bars": {},
                "provider": "alpaca",
                "feed": feed,
                "timeframe": timeframe,
                "session": "premarket",
                "start": premarket_start.astimezone(timezone.utc).isoformat(),
                "end": end.astimezone(timezone.utc).isoformat(),
                "partial": False,
                "available": False,
                "reason": "Premarket window has not started.",
            }

        result = self.stock_bars(
            user_id,
            symbols,
            start=premarket_start,
            end=end,
            timeframe=timeframe,
            feed=feed,
            adjustment="raw",
        )

        result.update(
            session="premarket",
            available=True,
            limitations=[
                (
                    "IEX is a single-exchange feed, not consolidated SIP. "
                    "Premarket volume from IEX must not be described as total US premarket volume."
                    if feed == "iex"
                    else "Feed completeness depends on the user's Alpaca market-data entitlement."
                )
            ],
        )

        return result


    def delayed_premarket_bars(
        self,
        user_id,
        symbols,
        *,
        now=None,
        timeframe="1Min",
        safe_delay_seconds=960,
    ):
        """Fetch consolidated SIP premarket minute history with a safe delay.

        The user's current Alpaca entitlement rejects recent SIP history. This
        method never asks the historical bars endpoint for the restricted recent
        window. The default safety delay is 16 minutes (960 seconds), slightly
        beyond the nominal 15-minute restriction.

        Window:
            04:00 America/New_York
            ->
            min(now - safe_delay, 09:30 America/New_York)

        Returned bars are real provider bars. They are explicitly DELAYED and
        must never be labeled real-time.
        """
        now = now or datetime.now(timezone.utc)

        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        try:
            safe_delay_seconds = int(safe_delay_seconds)
        except (TypeError, ValueError):
            raise ValueError("safe_delay_seconds must be an integer") from None

        # Never allow a caller to accidentally query inside the known 15m recent
        # SIP restriction. 16m is the Orion safety floor.
        safe_delay_seconds = max(960, safe_delay_seconds)

        eastern = ZoneInfo("America/New_York")
        now_utc = now.astimezone(timezone.utc)
        local_now = now_utc.astimezone(eastern)

        premarket_start = datetime.combine(
            local_now.date(),
            time(4, 0),
            tzinfo=eastern,
        )
        regular_open = datetime.combine(
            local_now.date(),
            time(9, 30),
            tzinfo=eastern,
        )

        safe_end_utc = now_utc - timedelta(seconds=safe_delay_seconds)
        safe_end_local = safe_end_utc.astimezone(eastern)

        # Before enough delayed premarket has accumulated, do not issue a SIP
        # historical request at all.
        if (
            safe_end_local.date() != local_now.date()
            or safe_end_local <= premarket_start
        ):
            return {
                "bars": {},
                "provider": "alpaca",
                "feed": "sip",
                "timeframe": timeframe,
                "session": "premarket",
                "available": False,
                "provider_available": True,
                "data_available": False,
                "delayed": True,
                "safe_delay_seconds": safe_delay_seconds,
                "delay_minutes_nominal": round(safe_delay_seconds / 60.0, 2),
                "start": premarket_start.astimezone(timezone.utc).isoformat(),
                "end": safe_end_utc.isoformat(),
                "as_of": safe_end_utc.isoformat(),
                "partial": False,
                "pages": 0,
                "reason": "Delayed SIP premarket window is not available yet.",
                "limitations": [
                    "Historical SIP is intentionally queried only outside the recent-data entitlement window."
                ],
            }

        end_local = min(safe_end_local, regular_open)

        if end_local <= premarket_start:
            return {
                "bars": {},
                "provider": "alpaca",
                "feed": "sip",
                "timeframe": timeframe,
                "session": "premarket",
                "available": False,
                "provider_available": True,
                "data_available": False,
                "delayed": True,
                "safe_delay_seconds": safe_delay_seconds,
                "delay_minutes_nominal": round(safe_delay_seconds / 60.0, 2),
                "start": premarket_start.astimezone(timezone.utc).isoformat(),
                "end": end_local.astimezone(timezone.utc).isoformat(),
                "as_of": end_local.astimezone(timezone.utc).isoformat(),
                "partial": False,
                "pages": 0,
                "reason": "No delayed premarket interval is available.",
            }

        result = self.stock_bars(
            user_id,
            symbols,
            start=premarket_start,
            end=end_local,
            timeframe=timeframe,
            feed="sip",
            adjustment="raw",
        )

        total_bars = sum(
            len(rows)
            for rows in (result.get("bars") or {}).values()
            if isinstance(rows, list)
        )

        result.update(
            session="premarket",
            available=bool(total_bars),
            provider_available=True,
            data_available=bool(total_bars),
            delayed=True,
            safe_delay_seconds=safe_delay_seconds,
            delay_minutes_nominal=round(safe_delay_seconds / 60.0, 2),
            as_of=end_local.astimezone(timezone.utc).isoformat(),
            total_bar_count=total_bars,
            reason=None if total_bars else "No delayed SIP premarket bars returned.",
            limitations=[
                "Consolidated SIP history is delayed by design to respect the current Alpaca entitlement.",
                "The most recent restricted SIP interval is intentionally excluded.",
            ],
        )

        return result


    def latest_stock_bars(
        self,
        user_id,
        symbols,
        *,
        feed="delayed_sip",
    ):
        """Fetch latest bar snapshots for a bounded symbol list.

        This is read-only market data. `delayed_sip` is explicitly treated as
        delayed consolidated data and must never be labeled live/current.
        """
        clean = list(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in symbols
                if symbol
            )
        )[:200]

        if not clean:
            return {
                "bars": {},
                "provider": "alpaca",
                "feed": feed,
                "delayed": feed == "delayed_sip",
            }

        if feed not in {"iex", "sip", "delayed_sip", "boats", "otc"}:
            raise ValueError("Unsupported Alpaca latest-bar feed")

        payload = self._request(
            user_id,
            "GET",
            "/v2/stocks/bars/latest",
            params={
                "symbols": ",".join(clean),
                "feed": feed,
            },
            data_api=True,
        )

        bars = payload.get("bars", {}) if isinstance(payload, dict) else {}

        return {
            "bars": bars if isinstance(bars, dict) else {},
            "provider": "alpaca",
            "feed": feed,
            "delayed": feed == "delayed_sip",
        }

    def premarket_snapshot_fallback(
        self,
        user_id,
        symbols,
        *,
        now=None,
    ):
        """Try current IEX snapshot first, then delayed SIP latest bar.

        This does not fabricate a minute history. It only returns a point-in-time
        market-data fallback that callers may use for gap/price context while
        preserving explicit delay metadata.
        """
        now = now or datetime.now(timezone.utc)

        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        clean = list(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in symbols
                if symbol
            )
        )[:200]

        if not clean:
            return {
                "provider": "alpaca",
                "mode": "unavailable",
                "symbols": {},
                "as_of": now.isoformat(),
                "delayed": None,
            }

        result = {
            "provider": "alpaca",
            "mode": "unavailable",
            "symbols": {},
            "as_of": now.isoformat(),
            "delayed": None,
            "warnings": [],
        }

        eastern = ZoneInfo("America/New_York")
        local_now = now.astimezone(eastern)
        pm_start = datetime.combine(
            local_now.date(),
            time(4, 0),
            tzinfo=eastern,
        )
        regular_open = datetime.combine(
            local_now.date(),
            time(9, 30),
            tzinfo=eastern,
        )

        def parse_stamp(value):
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")
                )
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc)

        def is_current_premarket_stamp(value, *, max_age_seconds):
            parsed = parse_stamp(value)
            if parsed is None:
                return False, None, None

            local_stamp = parsed.astimezone(eastern)
            age_seconds = (now.astimezone(timezone.utc) - parsed).total_seconds()

            valid_window = (
                local_stamp.date() == local_now.date()
                and pm_start <= local_stamp < regular_open
                and parsed <= now.astimezone(timezone.utc)
            )
            fresh_enough = 0 <= age_seconds <= max_age_seconds

            return valid_window and fresh_enough, parsed, age_seconds

        # 1) Current IEX snapshots.
        try:
            snapshots = self.snapshots(user_id, clean)
        except Exception as exc:
            snapshots = {}
            result["warnings"].append(
                f"IEX snapshot unavailable: {type(exc).__name__}"
            )

        current_found = False

        for symbol in clean:
            raw = snapshots.get(symbol)

            if not isinstance(raw, dict):
                continue

            trade = raw.get("latestTrade") or {}
            quote = raw.get("latestQuote") or {}

            price = trade.get("p")
            stamp = trade.get("t") or quote.get("t")

            if price is None:
                continue

            valid, parsed_stamp, age_seconds = is_current_premarket_stamp(
                stamp,
                max_age_seconds=300,
            )

            if not valid:
                result["warnings"].append(
                    f"{symbol}: IEX snapshot rejected because it is not a fresh "
                    "current-day premarket observation."
                )
                continue

            result["symbols"][symbol] = {
                "price": price,
                "timestamp": parsed_stamp.isoformat(),
                "source": "iex_snapshot",
                "delayed": False,
                "age_seconds": round(age_seconds, 1),
            }
            current_found = True

        if current_found:
            result["mode"] = "iex_snapshot"
            result["delayed"] = False
            return result

        # 2) Delayed consolidated SIP latest bars.
        try:
            delayed = self.latest_stock_bars(
                user_id,
                clean,
                feed="delayed_sip",
            )
        except Exception as exc:
            result["warnings"].append(
                f"Delayed SIP latest bar unavailable: {type(exc).__name__}"
            )
            return result

        delayed_bars = delayed.get("bars") or {}

        for symbol in clean:
            bar = delayed_bars.get(symbol)

            if not isinstance(bar, dict):
                continue

            price = bar.get("c")
            stamp = bar.get("t")

            if price is None:
                continue

            valid, parsed_stamp, age_seconds = is_current_premarket_stamp(
                stamp,
                max_age_seconds=30 * 60,
            )

            if not valid:
                result["warnings"].append(
                    f"{symbol}: delayed SIP bar rejected because it is not a "
                    "current-day premarket observation within the allowed delay window."
                )
                continue

            result["symbols"][symbol] = {
                "price": price,
                "timestamp": parsed_stamp.isoformat(),
                "source": "delayed_sip_latest_bar",
                "delayed": True,
                "age_seconds": round(age_seconds, 1),
            }

        if result["symbols"]:
            result["mode"] = "delayed_sip"
            result["delayed"] = True
            result["delay_minutes_nominal"] = 15
            result["maximum_accepted_age_minutes"] = 30

        return result

    def news(self, user_id, symbols, limit=50):
        clean = list(dict.fromkeys(
            str(symbol).strip().upper() for symbol in symbols if symbol
        ))[:50]
        if not clean:
            return {"news": [], "next_page_token": None}
        payload = self._request(
            user_id,
            "GET",
            "/v1beta1/news",
            params={
                "symbols": ",".join(clean),
                "limit": max(1, min(int(limit), 50)),
                "sort": "desc",
                "include_content": "false",
            },
            data_api=True,
        )
        return {
            "news": payload.get("news", []) if isinstance(payload, dict) else [],
            "next_page_token": payload.get("next_page_token") if isinstance(payload, dict) else None,
            "feed_mode": "authenticated_rest_snapshot",
        }

    def corporate_actions(self, user_id, symbols, start=None, end=None):
        clean = list(dict.fromkeys(
            str(symbol).strip().upper() for symbol in symbols if symbol
        ))[:50]
        if not clean:
            return {"corporate_actions": {}}
        params = {"symbols": ",".join(clean), "limit": 100}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        payload = self._request(
            user_id, "GET", "/v1/corporate-actions",
            params=params, data_api=True,
        )
        return payload if isinstance(payload, dict) else {"corporate_actions": {}}

    def submit_order(self, user_id, symbol, qty, side, order_type, time_in_force, limit_price, confirmed=False):
        if os.getenv("ALPACA_ORDER_SUBMISSION_ENABLED", "false").lower() != "true":
            raise ValueError("Alpaca order submission is disabled by server policy")
        if confirmed is not True:
            raise ValueError("Paper order confirmation is required")
        side, order_type, time_in_force = side.lower(), order_type.lower(), time_in_force.lower()
        if side not in {"buy", "sell"} or order_type not in {"market", "limit"} or time_in_force not in {"day", "gtc"}:
            raise ValueError("Unsupported paper order parameters")
        if float(qty) <= 0:
            raise ValueError("Order quantity must be greater than 0")
        if order_type == "limit" and (limit_price is None or float(limit_price) <= 0):
            raise ValueError("Limit orders require a positive limit price")
        payload = {"symbol": str(symbol).strip().upper(), "qty": str(qty), "side": side, "type": order_type, "time_in_force": time_in_force, "client_order_id": f"orion-{user_id[:8]}-{secrets.token_hex(8)}"}
        if order_type == "limit": payload["limit_price"] = str(limit_price)
        return self._request(user_id, "POST", "/v2/orders", payload)

    def submit_autonomous_order(self, user_id, symbol, qty, side, limit_price):
        if os.getenv("ALPACA_ORDER_SUBMISSION_ENABLED", "false").lower() != "true":
            raise ValueError("Alpaca order submission is disabled by server policy")
        if os.getenv("ORION_AUTONOMY_ENABLED", "false").lower() != "true":
            raise ValueError("Orion autonomous execution is disabled by server policy")
        if side not in {"buy", "sell"}:
            raise ValueError("Autonomous paper orders must be buy or sell")
        if float(qty) <= 0 or float(limit_price) <= 0:
            raise ValueError("Autonomous paper orders require positive quantity and limit price")
        payload = {
            "symbol": str(symbol).strip().upper(), "qty": str(qty), "side": side,
            "type": "limit", "time_in_force": "day", "limit_price": str(round(float(limit_price), 2)),
            "client_order_id": f"orion-auto-{user_id[:8]}-{secrets.token_hex(8)}",
        }
        return self._request(user_id, "POST", "/v2/orders", payload)

    def cancel_autonomous_orders(self, user_id):
        orders = self._request(user_id, "GET", "/v2/orders", params={"status": "open", "limit": 500})
        cancelled = []
        for order in orders:
            if str(order.get("client_order_id", "")).startswith("orion-auto-"):
                self._request(user_id, "DELETE", f"/v2/orders/{order['id']}")
                cancelled.append(order["id"])
        return cancelled

    @staticmethod
    def _safe_account(account):
        fields = ["id", "account_number", "status", "currency", "cash", "portfolio_value", "buying_power", "equity", "last_equity", "pattern_day_trader", "trading_blocked"]
        return {field: account.get(field) for field in fields}
