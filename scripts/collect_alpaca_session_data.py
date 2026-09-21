from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
CONTRACT = "orion-market-session-data-v1"
COLLECTOR_VERSION = "alpaca-session-reconciliation-v1"
FIELDNAMES = ("ticker", "timestamp", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class SessionWindow:
    name: str
    start: time
    end: time


SESSION_WINDOWS = {
    "premarket": SessionWindow("premarket", time(4, 0), time(9, 30)),
    "regular": SessionWindow("regular", time(9, 30), time(16, 0)),
    "after_hours": SessionWindow("after_hours", time(16, 0), time(20, 0)),
}


def session_window_from_calendar(
    session: str, calendar_entry: dict | None
) -> SessionWindow:
    base = SESSION_WINDOWS[session]
    if not calendar_entry:
        return base

    def parsed_clock(name: str, fallback: time) -> time:
        raw = str(calendar_entry.get(name) or "")
        try:
            return time.fromisoformat(raw)
        except ValueError:
            return fallback

    market_open = parsed_clock("open", time(9, 30))
    market_close = parsed_clock("close", time(16, 0))
    if session == "premarket":
        return SessionWindow(session, time(4, 0), market_open)
    if session == "regular":
        return SessionWindow(session, market_open, market_close)
    return SessionWindow(session, market_close, time(20, 0))


def utc_bounds(session_date: date, window: SessionWindow) -> tuple[str, str]:
    start = datetime.combine(session_date, window.start, tzinfo=NY)
    end = datetime.combine(session_date, window.end, tzinfo=NY)
    return (
        start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def rows_for_session(rows: list[dict], session_date: date, window: SessionWindow) -> list[dict]:
    accepted: list[dict] = []
    for row in rows:
        stamp = row.get("t")
        if not stamp:
            continue
        try:
            observed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        local = observed.astimezone(NY)
        local_clock = local.time().replace(tzinfo=None)
        if local.date() != session_date or not (window.start <= local_clock < window.end):
            continue
        if any(row.get(field) is None for field in ("o", "h", "l", "c", "v")):
            continue
        accepted.append(row)
    return sorted(accepted, key=lambda item: str(item["t"]))


def normalized_rows(
    grouped: dict[str, list[dict]], session_date: date, window: SessionWindow
) -> list[dict]:
    output: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ticker in sorted(grouped):
        for row in rows_for_session(grouped[ticker], session_date, window):
            key = (ticker, str(row["t"]))
            if key in seen:
                continue
            seen.add(key)
            output.append(
                {
                    "ticker": ticker,
                    "timestamp": key[1],
                    "open": row["o"],
                    "high": row["h"],
                    "low": row["l"],
                    "close": row["c"],
                    "volume": row["v"],
                }
            )
    return output


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_receipt(
    *,
    output: Path,
    rows: list[dict],
    symbols: list[str],
    session_date: date,
    window: SessionWindow,
    feed: str,
    collected_at_utc: str,
    github_run_id: str | None,
    github_run_attempt: str | None,
    github_head_sha: str | None,
    market_day: bool = True,
) -> dict:
    counts = {symbol: 0 for symbol in symbols}
    for row in rows:
        counts[str(row["ticker"])] += 1
    observed_symbols = sorted(symbol for symbol, count in counts.items() if count > 0)
    timestamps = sorted(str(row["timestamp"]) for row in rows)
    full_symbol_coverage = len(observed_symbols) == len(symbols)
    data_valid = bool(rows) and full_symbol_coverage
    receipt_valid = (not market_day) or data_valid
    eligible = market_day and data_valid
    return {
        "contract": CONTRACT,
        "collector_version": COLLECTOR_VERSION,
        "source": "alpaca_stock_bars_v2",
        "feed": feed,
        "timeframe": "1Min",
        "adjustment": "raw",
        "session": window.name,
        "session_date": session_date.isoformat(),
        "timezone": "America/New_York",
        "session_window_local": f"{window.start:%H:%M}-{window.end:%H:%M}",
        "market_day": market_day,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "observed_symbols": observed_symbols,
        "symbol_bar_counts": counts,
        "row_count": len(rows),
        "first_observed_bar_utc": timestamps[0] if timestamps else None,
        "last_observed_bar_utc": timestamps[-1] if timestamps else None,
        "collected_at_utc": collected_at_utc,
        "csv_sha256": sha256(output),
        "github_run_id": github_run_id,
        "github_run_attempt": int(github_run_attempt or "0"),
        "github_head_sha": github_head_sha,
        "valid": receipt_valid,
        "self_improvement_eligible": eligible,
        "eligibility_reason": (
            "validated_complete_symbol_coverage"
            if eligible
            else "market_closed"
            if not market_day
            else "missing_session_data"
        ),
        "order_submission_enabled": False,
    }


def main() -> int:
    import httpx

    from collect_alpaca_extended_history import (
        alpaca_bars,
        chunks,
        load_local_env,
        parse_symbols,
        resolve_credentials,
    )

    parser = argparse.ArgumentParser(description="Collect one completed US equity market session from Alpaca.")
    parser.add_argument("--session", choices=tuple(SESSION_WINDOWS), required=True)
    parser.add_argument("--session-date", required=True, help="US market date YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    load_local_env()
    key_id, secret_key = resolve_credentials()
    symbols = parse_symbols(args.symbols)
    market_date = date.fromisoformat(args.session_date)
    window = SESSION_WINDOWS[args.session]
    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    }
    grouped = {symbol: [] for symbol in symbols}
    with httpx.Client(timeout=30.0) as client:
        calendar_response = client.get(
            "https://paper-api.alpaca.markets/v2/calendar",
            headers=headers,
            params={"start": market_date.isoformat(), "end": market_date.isoformat()},
        )
        calendar_response.raise_for_status()
        calendar_payload = calendar_response.json()
        market_day = isinstance(calendar_payload, list) and bool(calendar_payload)
        if market_day:
            window = session_window_from_calendar(args.session, calendar_payload[0])
            start, end = utc_bounds(market_date, window)
            for symbol_batch in chunks(symbols, args.batch_size):
                batch = alpaca_bars(
                    client,
                    headers,
                    symbol_batch,
                    start=start,
                    end=end,
                    feed=args.feed,
                    max_pages=args.max_pages,
                )
                for symbol, values in batch.items():
                    grouped[symbol].extend(values)

    rows = normalized_rows(grouped, market_date, window)
    write_csv(args.output, rows)
    receipt = build_receipt(
        output=args.output,
        rows=rows,
        symbols=symbols,
        session_date=market_date,
        window=window,
        feed=args.feed,
        collected_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        github_run_id=os.getenv("GITHUB_RUN_ID"),
        github_run_attempt=os.getenv("GITHUB_RUN_ATTEMPT"),
        github_head_sha=os.getenv("GITHUB_SHA"),
        market_day=market_day,
    )
    receipt_path = args.output.with_suffix(".receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if not receipt["valid"]:
        raise SystemExit("Collected session failed validation; refusing self-improvement eligibility")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
