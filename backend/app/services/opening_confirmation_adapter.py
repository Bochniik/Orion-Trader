from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from app.services.opening_confirmation_engine import evaluate_opening_confirmation
from app.services.market_integrity_engine import analyze_market_integrity


NEW_YORK = ZoneInfo("America/New_York")


def alpaca_bars_to_frame(rows: Any) -> Optional[pd.DataFrame]:
    if not isinstance(rows, list) or not rows:
        return None

    parsed = []

    for row in rows:
        if not isinstance(row, dict) or not row.get("t"):
            continue

        parsed.append({
            "timestamp": row.get("t"),
            "Open": row.get("o"),
            "High": row.get("h"),
            "Low": row.get("l"),
            "Close": row.get("c"),
            "Volume": row.get("v"),
        })

    if not parsed:
        return None

    frame = pd.DataFrame(parsed)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"])

    for column in ["Open", "High", "Low", "Close", "Volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(
        subset=["Open", "High", "Low", "Close", "Volume"]
    )

    if frame.empty:
        return None

    return (
        frame.sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .set_index("timestamp")
    )[["Open", "High", "Low", "Close", "Volume"]]


class OpeningConfirmationAdapter:
    """Fetch bounded regular-session IEX bars for existing premarket candidates."""

    def __init__(self, broker):
        self.broker = broker

    def build(
        self,
        user_id: str,
        premarket_item: Dict[str, Any],
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)

        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        ticker = str(premarket_item.get("ticker") or "").strip().upper()

        if not ticker:
            raise ValueError("premarket item ticker is required")

        local_now = now.astimezone(NEW_YORK)
        open_dt = datetime.combine(
            local_now.date(),
            time(9, 30),
            tzinfo=NEW_YORK,
        )

        end_dt = min(
            local_now,
            datetime.combine(
                local_now.date(),
                time(10, 15),
                tzinfo=NEW_YORK,
            ),
        )

        if end_dt <= open_dt:
            return {
                "ticker": ticker,
                "setup_state": "WAIT",
                "confirmation_score": None,
                "confirmation_required": True,
                "reason": "Regular session has not opened yet.",
            }

        payload = self.broker.stock_bars(
            user_id,
            [ticker],
            start=open_dt,
            end=end_dt,
            timeframe="1Min",
            feed="iex",
            adjustment="raw",
        )

        rows = (payload.get("bars") or {}).get(ticker, [])
        frame = alpaca_bars_to_frame(rows)

        result = evaluate_opening_confirmation(
            premarket_item,
            frame,
            now=now,
        )

        result["market_integrity"] = analyze_market_integrity(
            ticker,
            frame,
            news_score=(
                (premarket_item.get("premarket_context") or {}).get("news_score")
                if isinstance(premarket_item.get("premarket_context"), dict)
                else None
            ),
            average_dollar_volume=premarket_item.get("baseline_dollar_volume"),
            now=now,
        )

        result.update(
            provider="alpaca",
            feed="iex",
            delayed=False,
            provider_partial=bool(payload.get("partial")),
            provider_pages=payload.get("pages"),
            as_of=now.isoformat(),
        )

        return result

    def build_many(
        self,
        user_id: str,
        premarket_items: Iterable[Dict[str, Any]],
        *,
        now: Optional[datetime] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        failures = []

        for item in list(premarket_items or [])[: max(1, int(limit))]:
            ticker = str((item or {}).get("ticker") or "").strip().upper()

            try:
                result = self.build(
                    user_id,
                    item,
                    now=now,
                )
                items.append(result)
            except Exception as exc:
                failures.append({
                    "ticker": ticker,
                    "reason": type(exc).__name__,
                })

        items.sort(
            key=lambda row: (
                0 if row.get("setup_state") == "OPEN_CONFIRMED" else
                1 if row.get("setup_state") == "WAIT" else 2,
                -(row.get("confirmation_score") or 0.0),
                row.get("ticker") or "",
            )
        )

        return {
            "items": items,
            "evaluated": len(items),
            "confirmed_count": sum(
                1 for item in items
                if item.get("setup_state") == "OPEN_CONFIRMED"
            ),
            "wait_count": sum(
                1 for item in items
                if item.get("setup_state") == "WAIT"
            ),
            "invalidated_count": sum(
                1 for item in items
                if item.get("setup_state") == "INVALIDATED"
            ),
            "failures": failures,
            "provider": "alpaca",
            "feed": "iex",
            "semantics": (
                "Opening confirmation evaluates only existing premarket research "
                "candidates during the early regular session. It is not a universe scan."
            ),
        }
