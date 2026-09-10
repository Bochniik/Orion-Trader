from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, time, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time as time_module
from typing import Iterable
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
DATA_URL = "https://data.alpaca.markets"
COLLECTOR_VERSION = "alpaca-extended-history-v2"


def load_local_env() -> None:
    for candidate in (ROOT / ".env", ROOT / "backend" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def resolve_credentials() -> tuple[str, str]:
    key = (
        os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("APCA_API_KEY_ID")
        or os.getenv("ALPACA_KEY_ID")
        or ""
    ).strip()
    secret = (
        os.getenv("ALPACA_API_SECRET_KEY")
        or os.getenv("APCA_API_SECRET_KEY")
        or os.getenv("ALPACA_SECRET_KEY")
        or ""
    ).strip()
    if not key or not secret:
        raise RuntimeError(
            "Alpaca credentials not found. Put ALPACA_API_KEY_ID and "
            "ALPACA_API_SECRET_KEY in backend/.env (or set APCA_API_KEY_ID / "
            "APCA_API_SECRET_KEY in PowerShell) and run again."
        )
    return key, secret


def parse_symbols(values: Iterable[str]) -> list[str]:
    symbols: list[str] = []
    for value in values:
        for item in str(value).split(","):
            symbol = item.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    if not symbols:
        raise ValueError("At least one ticker is required")
    return symbols


def chunks(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def date_chunks(start: date, end: date, days: int):
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=days - 1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def request_window(start_day: date, end_day: date) -> tuple[str, str]:
    # Request from premarket start through regular close. This intentionally
    # excludes after-hours so the raw dataset stays compact and the prior-close
    # reference remains unambiguous. DST is handled by America/New_York.
    start_local = datetime.combine(start_day, time(4, 0), tzinfo=NY)
    end_local = datetime.combine(end_day, time(16, 1), tzinfo=NY)
    return (
        start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def alpaca_bars(
    client: httpx.Client,
    headers: dict[str, str],
    symbols: list[str],
    *,
    start: str,
    end: str,
    feed: str,
    max_pages: int,
) -> dict[str, list[dict]]:
    grouped = {symbol: [] for symbol in symbols}
    page_token = None
    pages = 0

    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Min",
            "start": start,
            "end": end,
            "limit": 10000,
            "adjustment": "raw",
            "feed": feed,
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token

        response = client.get(
            f"{DATA_URL}/v2/stocks/bars",
            headers=headers,
            params=params,
        )

        if response.status_code == 429:
            retry_after = float(response.headers.get("retry-after") or 2.0)
            print(f"Rate limited; waiting {retry_after:.1f}s...", flush=True)
            time_module.sleep(max(1.0, retry_after))
            continue

        if response.status_code >= 400:
            try:
                detail = response.json().get("message")
            except Exception:
                detail = response.text
            raise RuntimeError(
                f"Alpaca data API error {response.status_code}: {detail}"
            )

        payload = response.json() if response.content else {}
        bars = payload.get("bars", {}) if isinstance(payload, dict) else {}
        if isinstance(bars, dict):
            for symbol, rows in bars.items():
                if symbol in grouped and isinstance(rows, list):
                    grouped[symbol].extend(row for row in rows if isinstance(row, dict))

        pages += 1
        page_token = payload.get("next_page_token") if isinstance(payload, dict) else None
        if not page_token:
            break
        if pages >= max_pages:
            raise RuntimeError(
                f"Pagination limit reached with more data remaining for {symbols}. "
                "Reduce --chunk-days or --batch-size."
            )

    return grouped


def filter_training_hours(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        stamp = row.get("t")
        if not stamp:
            continue
        try:
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        local = dt.astimezone(NY)
        local_time = local.time().replace(tzinfo=None)
        if time(4, 0) <= local_time < time(16, 0):
            result.append(row)
    return result


def load_existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ticker = str(row.get("ticker") or "").upper().strip()
            timestamp = str(row.get("timestamp") or "").strip()
            if ticker and timestamp:
                keys.add((ticker, timestamp))
    return keys


def append_rows(path: Path, grouped: dict[str, list[dict]], existing: set[tuple[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["ticker", "timestamp", "open", "high", "low", "close", "volume"]
    write_header = not path.exists() or path.stat().st_size == 0
    written = 0

    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for ticker in sorted(grouped):
            rows = filter_training_hours(grouped[ticker])
            rows.sort(key=lambda item: str(item.get("t") or ""))
            for row in rows:
                timestamp = str(row.get("t") or "")
                key = (ticker, timestamp)
                if not timestamp or key in existing:
                    continue

                required = [row.get("o"), row.get("h"), row.get("l"), row.get("c"), row.get("v")]
                if any(value is None for value in required):
                    continue

                writer.writerow({
                    "ticker": ticker,
                    "timestamp": timestamp,
                    "open": row.get("o"),
                    "high": row.get("h"),
                    "low": row.get("l"),
                    "close": row.get("c"),
                    "volume": row.get("v"),
                })
                existing.add(key)
                written += 1

    return written


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_collection_manifest(
    output: Path,
    *,
    symbols: list[str],
    start_day: date,
    end_day: date,
    feed: str,
    row_count: int,
    rows_added: int,
) -> Path:
    """Write a credential-free provenance sidecar for the collected raw CSV."""
    if not output.exists():
        raise FileNotFoundError(output)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    payload = {
        "collector_version": COLLECTOR_VERSION,
        "source": "alpaca_stock_bars_v2",
        "feed": feed,
        "adjustment": "raw",
        "timeframe": "1Min",
        "timezone": "America/New_York",
        "included_local_hours": "04:00-15:59",
        "requested_start": start_day.isoformat(),
        "requested_end": end_day.isoformat(),
        "symbols": symbols,
        "symbol_count": len(symbols),
        "row_count": int(row_count),
        "rows_added_last_run": int(rows_added),
        "schema": ["ticker", "timestamp", "open", "high", "low", "close", "volume"],
        "csv_sha256": file_sha256(output),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect historical 1-minute Alpaca bars for Orion's premarket predictive training dataset. "
            "The collector saves only 04:00-16:00 America/New_York bars and can resume into an existing CSV."
        )
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="Tickers, space- or comma-separated")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--batch-size", type=int, default=10, help="Tickers per API request (1-50)")
    parser.add_argument("--chunk-days", type=int, default=5, help="Calendar days per request window")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--pause", type=float, default=0.15, help="Pause between request batches")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/raw/alpaca_extended_minutes.csv"),
    )
    args = parser.parse_args()

    load_local_env()
    key_id, secret_key = resolve_credentials()
    symbols = parse_symbols(args.symbols)
    start_day = date.fromisoformat(args.start)
    end_day = date.fromisoformat(args.end)

    if end_day < start_day:
        raise ValueError("--end must be on or after --start")
    if not 1 <= args.batch_size <= 50:
        raise ValueError("--batch-size must be in [1, 50]")
    if args.chunk_days < 1:
        raise ValueError("--chunk-days must be >= 1")

    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    }
    existing = load_existing_keys(args.output)
    total_written = 0

    print(
        f"Collecting {len(symbols)} tickers from {start_day} to {end_day} via {args.feed.upper()}...",
        flush=True,
    )
    print(f"Output: {args.output} ({len(existing):,} existing rows)", flush=True)

    with httpx.Client(timeout=30.0) as client:
        for window_start, window_end in date_chunks(start_day, end_day, args.chunk_days):
            start_iso, end_iso = request_window(window_start, window_end)
            for symbol_batch in chunks(symbols, args.batch_size):
                print(
                    f"{window_start} -> {window_end} | {','.join(symbol_batch)}",
                    flush=True,
                )
                grouped = alpaca_bars(
                    client,
                    headers,
                    symbol_batch,
                    start=start_iso,
                    end=end_iso,
                    feed=args.feed,
                    max_pages=args.max_pages,
                )
                written = append_rows(args.output, grouped, existing)
                total_written += written
                print(f"  +{written:,} rows", flush=True)
                if args.pause > 0:
                    time_module.sleep(args.pause)

    manifest_path = write_collection_manifest(
        args.output,
        symbols=symbols,
        start_day=start_day,
        end_day=end_day,
        feed=args.feed,
        row_count=len(existing),
        rows_added=total_written,
    )
    print(
        f"Done. Added {total_written:,} rows; CSV now contains {len(existing):,} unique ticker-minute rows.",
        flush=True,
    )
    print(f"Provenance manifest: {manifest_path}", flush=True)
    print(
        "Next: python scripts/build_premarket_training_dataset.py "
        f"{args.output} --output backend/data/premarket_training_dataset.csv",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user. Existing CSV progress is preserved.", file=sys.stderr)
        raise SystemExit(130)
