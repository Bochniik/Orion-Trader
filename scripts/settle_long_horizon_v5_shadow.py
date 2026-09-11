from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable

import httpx

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from collect_cloud_shadow_outcome_bars import (
    build_request_windows,
    fetch_window,
    resolve_credentials,
    write_bars,
)
from evaluate_cloud_shadow_predictions import (
    ForecastRecord,
    grouped_summaries,
    horizon_minutes,
    load_bars,
    parse_iso,
    settle_forecast,
    summarize,
)

CONTRACT = "orion-long-horizon-v5-paired-shadow-v1"
EVALUATION_CONTRACT = "orion-cloud-shadow-evaluation-v1"


def expand_payload(payload: dict[str, Any], source_file: str) -> list[dict[str, Any]]:
    if payload.get("contract") != CONTRACT:
        raise ValueError(f"Unsupported paired shadow contract: {payload.get('contract')}")
    lineage = dict(payload.get("lineage") or {})
    forecasts: list[dict[str, Any]] = []
    for row in payload.get("paired_predictions") or []:
        if not isinstance(row, dict):
            continue
        for side in ("incumbent", "challenger"):
            model = row.get(side) or {}
            if not isinstance(model, dict) or model.get("probability_up") is None:
                continue
            model_lineage = dict(lineage)
            model_lineage["paired_role"] = side
            model_lineage["engine"] = model.get("engine")
            forecasts.append({
                "source_file": source_file,
                "engine": str(model.get("engine")),
                "symbol": str(row.get("symbol") or "").upper(),
                "horizon": str(row.get("horizon")),
                "prediction_time": row.get("prediction_time_utc"),
                "probability_up": float(model.get("probability_up")),
                "direction": model.get("direction"),
                "lineage": model_lineage,
                "reliability_profile_source": None,
                "profile_validated_for_symbol": None,
            })
    return forecasts


def load_forecasts(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(expand_payload(payload, str(path)))
    return rows


def _dedupe_windows(windows):
    by_key = {}
    for window in windows:
        key = (window.symbol, window.start_utc, window.end_utc)
        if key not in by_key:
            by_key[key] = window
    return list(by_key.values())


def collect_bars(forecasts: list[dict[str, Any]], *, cutoff: datetime, output: Path, feed: str) -> dict[str, Any]:
    windows, stats = build_request_windows(forecasts, cutoff=cutoff)
    unique_windows = _dedupe_windows(windows)
    key, secret = resolve_credentials()
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    fetched = []
    with httpx.Client(timeout=30.0) as client:
        for window in unique_windows:
            fetched.append((window, fetch_window(client, headers, window, feed=feed)))
    bar_count = write_bars(output, fetched)
    return {
        "request_windows": len(unique_windows),
        "bar_count": bar_count,
        "forecast_window_stats": stats,
    }


def settle(forecasts: list[dict[str, Any]], bars_path: Path, cutoff: datetime) -> dict[str, Any]:
    bars = load_bars(bars_path)
    mature = []
    settled: list[ForecastRecord] = []

    for forecast in forecasts:
        prediction_time = parse_iso(str(forecast["prediction_time"]))
        target_time = prediction_time + timedelta(minutes=horizon_minutes(str(forecast["horizon"])))
        if target_time > cutoff:
            continue
        mature.append(forecast)
        record = settle_forecast(forecast, bars, cutoff)
        if record is not None:
            settled.append(record)

    return {
        "contract": EVALUATION_CONTRACT,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_cutoff_utc": cutoff.isoformat(),
        "leakage_safe": True,
        "research_only": True,
        "paired_long_horizon_v5": True,
        "summary": summarize(settled, len(mature)),
        "by_engine_horizon": grouped_summaries(settled),
        "records": [asdict(row) for row in settled],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch bounded outcomes and settle paired V3.1/V5 forward-shadow forecasts.")
    parser.add_argument("predictions", nargs="+", type=Path)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--feed", default="iex")
    parser.add_argument("--bars-output", type=Path, default=Path("backend/data/cloud_shadow/long_horizon_v5/outcome-bars.csv"))
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/long_horizon_v5/evaluation.json"))
    args = parser.parse_args()

    cutoff = parse_iso(args.as_of) if args.as_of else datetime.now(timezone.utc)
    forecasts = load_forecasts(args.predictions)
    diagnostics = collect_bars(forecasts, cutoff=cutoff, output=args.bars_output, feed=args.feed)
    payload = settle(forecasts, args.bars_output, cutoff)
    payload["outcome_collection"] = diagnostics
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"summary": payload["summary"], "outcome_collection": diagnostics}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
