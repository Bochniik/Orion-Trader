
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from app.services.opportunity_learning_db import (
    OpportunityLearningJournal,
    learning_database_path,
)


NY = ZoneInfo("America/New_York")


def _dt(value: Any) -> Optional[datetime]:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(number):
        return None

    return number


def _download_1m_history(symbol: str) -> Optional[pd.DataFrame]:
    """
    Resolve outcomes from public historical bars.

    This is intentionally separated from the forecast engine. It never feeds
    future data back into the prediction that produced the record.
    """
    try:
        import yfinance as yf

        frame = yf.download(
            symbol,
            period="5d",
            interval="1m",
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )
    except Exception:
        return None

    if frame is None or frame.empty:
        return None

    if isinstance(frame.columns, pd.MultiIndex):
        if symbol in frame.columns.get_level_values(-1):
            try:
                frame = frame.xs(
                    symbol,
                    axis=1,
                    level=-1,
                    drop_level=True,
                )
            except Exception:
                pass

        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = [
                column[0]
                if isinstance(column, tuple)
                else column
                for column in frame.columns
            ]

    close_column = None

    for candidate in (
        "Close",
        "close",
        "Adj Close",
    ):
        if candidate in frame.columns:
            close_column = candidate
            break

    if close_column is None:
        return None

    result = pd.DataFrame(
        {
            "close": pd.to_numeric(
                frame[close_column],
                errors="coerce",
            )
        }
    ).dropna()

    if result.empty:
        return None

    index = pd.to_datetime(
        result.index,
        utc=True,
        errors="coerce",
    )

    result = result.loc[
        ~index.isna()
    ].copy()

    result.index = index[
        ~index.isna()
    ]

    return result.sort_index()


def _nearest_price(
    frame: pd.DataFrame,
    target: datetime,
    *,
    tolerance_minutes: int = 8,
) -> Optional[Dict[str, Any]]:
    if frame is None or frame.empty:
        return None

    target = target.astimezone(timezone.utc)

    index = frame.index
    location = index.get_indexer(
        [pd.Timestamp(target)],
        method="nearest",
        tolerance=pd.Timedelta(
            minutes=tolerance_minutes
        ),
    )[0]

    if location < 0:
        return None

    price = _finite(
        frame.iloc[location]["close"]
    )

    if price is None or price <= 0:
        return None

    stamp = frame.index[location].to_pydatetime()

    return {
        "price": price,
        "timestamp": stamp.isoformat(),
    }


def resolve_due_outcomes(
    journal: OpportunityLearningJournal,
    *,
    now: Optional[datetime] = None,
    max_forecasts: int = 12,
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)

    pending = journal.pending_forecasts(
        now=now.isoformat(),
        limit=max_forecasts,
    )

    if not pending:
        return {
            "checked": 0,
            "resolved": 0,
            "skipped": 0,
            "errors": [],
        }

    histories: Dict[str, Optional[pd.DataFrame]] = {}
    resolved = 0
    skipped = 0
    errors: List[str] = []

    for row in pending:
        symbol = str(row["symbol"]).upper()

        if symbol not in histories:
            histories[symbol] = _download_1m_history(
                symbol
            )

        frame = histories[symbol]

        if frame is None or frame.empty:
            skipped += 1
            continue

        observed_at = _dt(
            row.get("observed_at")
        )

        target_at = _dt(
            row.get("target_at")
        )

        if observed_at is None or target_at is None:
            skipped += 1
            continue

        # Same-session integrity check. We never silently use a next-day bar as
        # the outcome of an intraday forecast.
        if (
            observed_at.astimezone(NY).date()
            != target_at.astimezone(NY).date()
        ):
            skipped += 1
            continue

        start_price = _finite(
            row.get("reference_price")
        )

        start_source_timestamp = None

        if start_price is None or start_price <= 0:
            start = _nearest_price(
                frame,
                observed_at,
            )

            if start is None:
                skipped += 1
                continue

            start_price = start["price"]
            start_source_timestamp = start[
                "timestamp"
            ]

        end = _nearest_price(
            frame,
            target_at,
        )

        if end is None:
            skipped += 1
            continue

        try:
            journal.save_outcome(
                int(row["forecast_id"]),
                start_price=float(start_price),
                end_price=float(end["price"]),
                source="yfinance_1m_regular_session",
                source_timestamp=end["timestamp"],
                extra={
                    "start_source_timestamp": (
                        start_source_timestamp
                    ),
                    "target_at": target_at.isoformat(),
                },
            )
            resolved += 1

        except Exception as exc:
            errors.append(
                f"{symbol}:{row['forecast_horizon']}:"
                f"{type(exc).__name__}"
            )

    return {
        "checked": len(pending),
        "resolved": resolved,
        "skipped": skipped,
        "errors": errors,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=None,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
    )
    args = parser.parse_args()

    journal = OpportunityLearningJournal(
        args.db
        or learning_database_path()
    )

    result = resolve_due_outcomes(
        journal,
        max_forecasts=max(
            1,
            args.limit,
        ),
    )

    print(
        json.dumps(
            {
                "database": str(journal.db_path),
                **result,
                "counts": journal.counts(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
