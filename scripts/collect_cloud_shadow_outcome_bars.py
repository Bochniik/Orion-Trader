from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from evaluate_cloud_shadow_predictions import horizon_minutes, iter_forecasts, parse_iso


DATA_URL = "https://data.alpaca.markets"
WINDOW_PADDING = timedelta(minutes=5)
END_EXCLUSIVE_PADDING = timedelta(minutes=6)
DEFAULT_MAX_AGE_DAYS = 35


@dataclass(frozen=True)
class OutcomeWindow:
    engine: str
    symbol: str
    prediction_time_utc: str
    start_utc: str
    end_utc: str
    mature_horizons: tuple[str, ...]


def resolve_credentials() -> tuple[str, str]:
    key = (os.getenv("ALPACA_API_KEY_ID") or os.getenv("APCA_API_KEY_ID") or "").strip()
    secret = (os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or "").strip()
    if not key or not secret:
        raise RuntimeError("Missing Alpaca market-data credentials")
    return key, secret


def load_forecasts(paths: Iterable[Path]) -> list[dict[str, Any]]:
    forecasts: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        forecasts.extend(iter_forecasts(payload, str(path)))
    return forecasts


def build_request_windows(
    forecasts: Iterable[dict[str, Any]],
    *,
    cutoff: datetime,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> tuple[list[OutcomeWindow], dict[str, int]]:
    cutoff = cutoff.astimezone(timezone.utc)
    oldest_allowed = cutoff - timedelta(days=max_age_days)
    grouped: dict[tuple[str, str, datetime], list[tuple[str, datetime]]] = {}
    stats = {"forecasts_seen": 0, "future_horizon": 0, "too_old": 0, "mature": 0}

    for forecast in forecasts:
        stats["forecasts_seen"] += 1
        prediction_time = parse_iso(str(forecast["prediction_time"]))
        if prediction_time < oldest_allowed:
            stats["too_old"] += 1
            continue
        target_time = prediction_time + timedelta(minutes=horizon_minutes(str(forecast["horizon"])))
        if target_time > cutoff:
            stats["future_horizon"] += 1
            continue
        stats["mature"] += 1
        key = (str(forecast["engine"]), str(forecast["symbol"]), prediction_time)
        grouped.setdefault(key, []).append((str(forecast["horizon"]), target_time))

    windows: list[OutcomeWindow] = []
    for (engine, symbol, prediction_time), rows in grouped.items():
        latest_target = max(target for _, target in rows)
        horizons = tuple(sorted({label for label, _ in rows}, key=horizon_minutes))
        windows.append(
            OutcomeWindow(
                engine=engine,
                symbol=symbol,
                prediction_time_utc=prediction_time.isoformat(),
                start_utc=(prediction_time - WINDOW_PADDING).isoformat(),
                # Alpaca's end is exclusive. Six minutes includes the evaluator's
                # accepted bar exactly five minutes after the target timestamp.
                end_utc=(latest_target + END_EXCLUSIVE_PADDING).isoformat(),
                mature_horizons=horizons,
            )
        )
    windows.sort(key=lambda row: (row.start_utc, row.engine, row.symbol))
    return windows, stats


def fetch_window(
    client: httpx.Client,
    headers: dict[str, str],
    window: OutcomeWindow,
    *,
    feed: str,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    pages = 0
    while True:
        params = {
            "symbols": window.symbol,
            "timeframe": "1Min",
            "start": window.start_utc,
            "end": window.end_utc,
            "limit": 10000,
            "adjustment": "raw",
            "feed": feed,
            "sort": "asc",
        }
        if page_token:
            params["page_token"] = page_token
        response = client.get(f"{DATA_URL}/v2/stocks/bars", headers=headers, params=params)
        if response.status_code == 429:
            retry_after = float(response.headers.get("retry-after") or 2.0)
            time.sleep(max(1.0, retry_after))
            continue
        if response.status_code >= 400:
            try:
                detail = response.json().get("message")
            except Exception:
                detail = response.text
            raise RuntimeError(f"Alpaca data API error {response.status_code}: {detail}")
        payload = response.json() if response.content else {}
        bars = payload.get("bars", {}) if isinstance(payload, dict) else {}
        symbol_rows = bars.get(window.symbol, []) if isinstance(bars, dict) else []
        if isinstance(symbol_rows, list):
            rows.extend(row for row in symbol_rows if isinstance(row, dict))
        pages += 1
        page_token = payload.get("next_page_token") if isinstance(payload, dict) else None
        if not page_token:
            break
        if pages >= max_pages:
            raise RuntimeError(f"Pagination limit reached for {window.symbol} {window.start_utc}..{window.end_utc}")
    return rows


def write_bars(path: Path, windows_and_rows: Iterable[tuple[OutcomeWindow, list[dict[str, Any]]]]) -> int:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for window, rows in windows_and_rows:
        start = parse_iso(window.start_utc)
        end = parse_iso(window.end_utc)
        for row in rows:
            stamp_raw = row.get("t")
            if not stamp_raw:
                continue
            stamp = parse_iso(str(stamp_raw))
            if not (start <= stamp < end):
                continue
            close = row.get("c")
            if close is None:
                continue
            key = (window.symbol, stamp.isoformat())
            by_key[key] = {
                "ticker": window.symbol,
                "timestamp": stamp.isoformat(),
                "close": close,
            }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "timestamp", "close"])
        writer.writeheader()
        for key in sorted(by_key):
            writer.writerow(by_key[key])
    return len(by_key)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch only bounded Alpaca 1-minute outcome windows for mature Orion shadow forecasts.")
    parser.add_argument("predictions", nargs="+", type=Path)
    parser.add_argument("--as-of", default=None, help="UTC-aware evaluation cutoff; default current UTC")
    parser.add_argument("--feed", default="iex")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/evaluation/outcome-bars.csv"))
    parser.add_argument("--report", type=Path, default=Path("backend/data/cloud_shadow/evaluation/outcome-fetch-report.json"))
    args = parser.parse_args()

    cutoff = parse_iso(args.as_of) if args.as_of else datetime.now(timezone.utc)
    forecasts = load_forecasts(args.predictions)
    windows, stats = build_request_windows(forecasts, cutoff=cutoff, max_age_days=max(1, args.max_age_days))

    fetched: list[tuple[OutcomeWindow, list[dict[str, Any]]]] = []
    failures: list[dict[str, str]] = []
    if windows:
        key, secret = resolve_credentials()
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        with httpx.Client(timeout=30.0) as client:
            for window in windows:
                try:
                    fetched.append((window, fetch_window(client, headers, window, feed=args.feed)))
                except Exception as exc:
                    failures.append({"symbol": window.symbol, "start_utc": window.start_utc, "end_utc": window.end_utc, "error": str(exc)})

    rows_written = write_bars(args.output, fetched)
    report = {
        "contract": "orion-cloud-shadow-outcome-fetch-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_cutoff_utc": cutoff.isoformat(),
        "feed": args.feed,
        "bounded_windows": True,
        "max_age_days": max(1, args.max_age_days),
        "stats": {**stats, "request_windows": len(windows), "rows_written": rows_written, "failures": len(failures)},
        "windows": [asdict(window) for window in windows],
        "failures": failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["stats"], sort_keys=True))
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
