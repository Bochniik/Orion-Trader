

from datetime import datetime, time, timezone
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")

PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
AFTER_HOURS_END = time(20, 0)

SUPPORTED_MODES = {
    "premarket",
    "regular",
    "after_hours",
    "closed",
}


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return None

    if result.tzinfo is None:
        return None

    return result.astimezone(timezone.utc)


def _to_ny(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.astimezone(NEW_YORK)


def _calendar_session_for_date(
    calendar_rows: Optional[Iterable[Dict[str, Any]]],
    local_date,
) -> Optional[Dict[str, datetime]]:
    """
    Normalize one Alpaca calendar row for `local_date`.

    Expected calendar rows may contain:
        date
        open
        close

    `open` / `close` may be full ISO timestamps or HH:MM strings.
    """

    if not calendar_rows:
        return None

    for row in calendar_rows:
        if not isinstance(row, dict):
            continue

        raw_date = row.get("date")
        if raw_date is None:
            continue

        try:
            row_date = datetime.fromisoformat(
                str(raw_date)
            ).date()
        except (TypeError, ValueError):
            continue

        if row_date != local_date:
            continue

        def parse_calendar_time(
            value: Any,
            fallback: time,
        ) -> datetime:
            parsed = _parse_datetime(value)

            if parsed is not None:
                return parsed.astimezone(
                    NEW_YORK
                )

            raw = str(
                value or ""
            ).strip()

            parsed_time = fallback

            for fmt in (
                "%H:%M",
                "%H:%M:%S",
            ):
                try:
                    parsed_time = datetime.strptime(
                        raw,
                        fmt,
                    ).time()
                    break
                except ValueError:
                    pass

            return datetime.combine(
                local_date,
                parsed_time,
                tzinfo=NEW_YORK,
            )

        return {
            "open": parse_calendar_time(
                row.get("open"),
                REGULAR_OPEN,
            ),
            "close": parse_calendar_time(
                row.get("close"),
                REGULAR_CLOSE,
            ),
        }

    return None


def classify_market_session(
    *,
    now: Optional[datetime] = None,
    clock: Optional[Dict[str, Any]] = None,
    calendar_rows: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Determine Orion's market-research mode.

    This function is deterministic and network-free. It only interprets data
    already supplied by the caller.

    Modes:
        premarket     04:00 -> regular open on a verified trading day
        regular       Alpaca clock reports is_open=True
        after_hours   regular close -> 20:00 on a verified trading day
        closed        all other times

    A premarket/after-hours result is a RESEARCH mode. It does not imply that
    the regular-session setup is confirmed or actionable.
    """

    now = now or datetime.now(
        timezone.utc
    )

    if now.tzinfo is None:
        raise ValueError(
            "now must be timezone-aware"
        )

    now = now.astimezone(
        timezone.utc
    )

    local_now = now.astimezone(
        NEW_YORK
    )

    clock = (
        dict(clock)
        if isinstance(
            clock,
            dict,
        )
        else {}
    )

    is_open = clock.get(
        "is_open"
    )

    next_open = _parse_datetime(
        clock.get(
            "next_open"
        )
    )

    next_close = _parse_datetime(
        clock.get(
            "next_close"
        )
    )

    session = _calendar_session_for_date(
        calendar_rows,
        local_now.date(),
    )

    warnings = []

    # Alpaca's market clock is authoritative for the regular session.
    if is_open is True:
        mode = "regular"

        regular_open = (
            session["open"]
            if session
            else datetime.combine(
                local_now.date(),
                REGULAR_OPEN,
                tzinfo=NEW_YORK,
            )
        )

        regular_close = (
            session["close"]
            if session
            else (
                _to_ny(
                    next_close
                )
                or datetime.combine(
                    local_now.date(),
                    REGULAR_CLOSE,
                    tzinfo=NEW_YORK,
                )
            )
        )

    else:
        regular_open = (
            session["open"]
            if session
            else datetime.combine(
                local_now.date(),
                REGULAR_OPEN,
                tzinfo=NEW_YORK,
            )
        )

        regular_close = (
            session["close"]
            if session
            else datetime.combine(
                local_now.date(),
                REGULAR_CLOSE,
                tzinfo=NEW_YORK,
            )
        )

        if session is not None:
            # Calendar verification prevents holidays from being accidentally
            # classified as premarket / after-hours.
            if (
                PREMARKET_START
                <= local_now.time()
                < regular_open.time()
            ):
                mode = "premarket"

            elif (
                regular_close
                <= local_now
                < datetime.combine(
                    local_now.date(),
                    AFTER_HOURS_END,
                    tzinfo=NEW_YORK,
                )
            ):
                mode = "after_hours"

            else:
                mode = "closed"

        else:
            # Safe fallback when the calendar is temporarily unavailable.
            # Premarket can still be verified if Alpaca says the next open is
            # later TODAY. After-hours is left conservative because a weekday
            # alone cannot distinguish a holiday from a trading session.
            next_open_local = _to_ny(
                next_open
            )

            if (
                next_open_local is not None
                and next_open_local.date()
                == local_now.date()
                and PREMARKET_START
                <= local_now.time()
                < next_open_local.time()
            ):
                mode = "premarket"

                regular_open = (
                    next_open_local
                )

                warnings.append(
                    "Premarket inferred from Alpaca next_open because "
                    "today's calendar row was unavailable."
                )

            else:
                mode = "closed"

                if (
                    local_now.weekday() < 5
                    and REGULAR_CLOSE
                    <= local_now.time()
                    < AFTER_HOURS_END
                ):
                    warnings.append(
                        "After-hours was not activated because today's "
                        "trading-session calendar could not be verified."
                    )

    if mode not in SUPPORTED_MODES:
        raise RuntimeError(
            f"Unexpected market session mode: {mode}"
        )

    confirmation_required = (
        mode in {
            "premarket",
            "after_hours",
        }
    )

    if mode == "regular":
        status = "regular_session"
        label = "REGULAR"
        research_horizons = [
            "day",
            "swing",
            "long_term",
        ]

    elif mode == "premarket":
        status = "premarket_research"
        label = "PREMARKET"
        research_horizons = [
            "day",
            "swing",
            "long_term",
        ]

    elif mode == "after_hours":
        status = "after_hours_research"
        label = "AFTER HOURS"
        research_horizons = [
            "day",
            "swing",
            "long_term",
        ]

    else:
        status = "next_session_research"
        label = "CLOSED"
        research_horizons = [
            "swing",
            "long_term",
        ]

    if mode == "premarket":
        day_setup_state = (
            "WAIT_FOR_OPEN_CONFIRMATION"
        )
    elif mode == "after_hours":
        day_setup_state = (
            "NEXT_SESSION_RESEARCH"
        )
    elif mode == "regular":
        day_setup_state = (
            "REGULAR_SESSION"
        )
    else:
        day_setup_state = (
            "UNAVAILABLE_WHILE_CLOSED"
        )

    after_hours_end = datetime.combine(
        local_now.date(),
        AFTER_HOURS_END,
        tzinfo=NEW_YORK,
    )

    if mode == "premarket":
        next_transition = regular_open
        next_transition_kind = "regular_open"
        workflow_mode = "transition_research"
        ui_priority = "prepare_for_open"
        price_semantics = "extended_hours"
    elif mode == "regular":
        next_transition = regular_close
        next_transition_kind = "regular_close"
        workflow_mode = "live"
        ui_priority = "live_market"
        price_semantics = "live_regular"
    elif mode == "after_hours":
        next_transition = after_hours_end
        next_transition_kind = "extended_hours_end"
        workflow_mode = "transition_research"
        ui_priority = "review_and_prepare"
        price_semantics = "extended_hours"
    else:
        next_transition = _to_ny(next_open)
        next_transition_kind = "next_regular_open" if next_transition else None
        workflow_mode = "research"
        ui_priority = "research_review_preparation"
        price_semantics = "historical_or_delayed"

    verified = bool(
        is_open is True
        or session is not None
        or (
            is_open is False
            and next_open is not None
        )
    )

    return {
        "session_state_version": "orion-session-state-v2",
        "mode": mode,
        "label": label,
        "status": status,
        "verified": verified,
        "workflow_mode": workflow_mode,
        "ui_priority": ui_priority,
        "price_semantics": price_semantics,

        "as_of": now.isoformat(),
        "as_of_new_york": (
            local_now.isoformat()
        ),

        "regular_open": (
            regular_open.isoformat()
            if regular_open
            else None
        ),

        "regular_close": (
            regular_close.isoformat()
            if regular_close
            else None
        ),

        "next_open": (
            next_open.isoformat()
            if next_open
            else None
        ),

        "next_close": (
            next_close.isoformat()
            if next_close
            else None
        ),

        "next_transition": (
            next_transition.isoformat()
            if next_transition
            else None
        ),
        "next_transition_kind": next_transition_kind,

        "calendar_verified": (
            session is not None
        ),

        "regular_market_open": (
            is_open is True
        ),

        "extended_hours_research": (
            mode in {
                "premarket",
                "after_hours",
            }
        ),

        "confirmation_required": (
            confirmation_required
        ),

        "day_setup_state": (
            day_setup_state
        ),

        "research_horizons": (
            research_horizons
        ),

        "allowed_workflows": {
            "live_scanner": mode == "regular",
            "premarket_engine": mode == "premarket",
            "extended_hours_monitoring": mode in {"premarket", "after_hours"},
            "settlement_and_evaluation": mode != "regular",
            "research_lab": mode != "regular",
            "next_session_preparation": mode != "regular",
        },

        "warnings": warnings,

        "semantics": (
            "Premarket and after-hours outputs are research plans, not "
            "regular-session confirmation. Closed-session prices must be labelled "
            "historical or delayed and must never be presented as live regular-session data."
        ),
    }


def compact_session_state(
    result: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "session_state_version": result.get("session_state_version"),
        "mode": result.get("mode"),
        "label": result.get("label"),
        "status": result.get("status"),
        "verified": result.get("verified"),
        "workflow_mode": result.get("workflow_mode"),
        "ui_priority": result.get("ui_priority"),
        "price_semantics": result.get("price_semantics"),
        "next_open": result.get("next_open"),
        "next_transition": result.get("next_transition"),
        "next_transition_kind": result.get("next_transition_kind"),
        "confirmation_required": result.get("confirmation_required"),
        "day_setup_state": result.get("day_setup_state"),
        "research_horizons": result.get("research_horizons"),
        "allowed_workflows": result.get("allowed_workflows"),
    }


if __name__ == "__main__":
    import json

    # Deterministic examples; no network access.
    examples = {
        "premarket": classify_market_session(
            now=datetime(
                2026,
                9,
                4,
                12,
                15,
                tzinfo=timezone.utc,
            ),
            clock={
                "is_open": False,
                "next_open": "2026-09-04T13:30:00+00:00",
                "next_close": "2026-09-04T20:00:00+00:00",
            },
            calendar_rows=[
                {
                    "date": "2026-09-04",
                    "open": "09:30",
                    "close": "16:00",
                }
            ],
        ),

        "regular": classify_market_session(
            now=datetime(
                2026,
                9,
                4,
                15,
                0,
                tzinfo=timezone.utc,
            ),
            clock={
                "is_open": True,
                "next_close": "2026-09-04T20:00:00+00:00",
            },
            calendar_rows=[
                {
                    "date": "2026-09-04",
                    "open": "09:30",
                    "close": "16:00",
                }
            ],
        ),

        "after_hours": classify_market_session(
            now=datetime(
                2026,
                9,
                4,
                21,
                0,
                tzinfo=timezone.utc,
            ),
            clock={
                "is_open": False,
                "next_open": "2026-09-08T13:30:00+00:00",
            },
            calendar_rows=[
                {
                    "date": "2026-09-04",
                    "open": "09:30",
                    "close": "16:00",
                }
            ],
        ),

        "weekend": classify_market_session(
            now=datetime(
                2026,
                9,
                5,
                15,
                0,
                tzinfo=timezone.utc,
            ),
            clock={
                "is_open": False,
                "next_open": "2026-09-08T13:30:00+00:00",
            },
            calendar_rows=[],
        ),
    }

    print(
        json.dumps(
            examples,
            indent=2,
            ensure_ascii=False,
        )
    )
