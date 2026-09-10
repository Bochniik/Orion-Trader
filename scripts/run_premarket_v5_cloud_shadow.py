from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BACKEND = ROOT / "backend"
for candidate in (str(SCRIPTS), str(BACKEND)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from build_premarket_training_dataset import PREMARKET_START, REGULAR_OPEN, normalize_columns, previous_regular_close
from build_premarket_training_dataset_v2 import horizon_sigma_pct
from premarket_directional_v4_common import PREMARKET_TARGETS, engineer_row
from premarket_directional_v5_common import HybridModel, V5_FEATURE_NAMES
from app.services.premarket_predictive_engine import extract_predictive_features

NY = ZoneInfo("America/New_York")
RUNNER_VERSION = "premarket-v5-cloud-shadow-v1"
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")


def parse_symbols(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for raw in str(value).split(","):
            symbol = raw.strip().upper()
            if symbol and symbol not in result:
                result.append(symbol)
    if not result:
        raise ValueError("At least one symbol is required")
    return result


def parse_as_of(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--as-of must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def premarket_window_status(as_of: datetime) -> tuple[bool, str, datetime]:
    local = as_of.astimezone(NY)
    if local.weekday() >= 5:
        return False, "weekend", local
    clock = local.time().replace(tzinfo=None)
    if clock < PREMARKET_START:
        return False, "before_premarket", local
    if clock >= REGULAR_OPEN:
        return False, "regular_session_started", local
    return True, "premarket", local


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_checked(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def require_credentials() -> None:
    key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Alpaca credentials are required for cloud shadow collection")


def collect_and_train(*, symbols: list[str], as_of: datetime, raw_path: Path, dataset_path: Path, model_path: Path, lookback_days: int, feed: str) -> None:
    require_credentials()
    local_day = as_of.astimezone(NY).date()
    start_day = local_day - timedelta(days=lookback_days)
    run_checked([
        sys.executable,
        str(SCRIPTS / "collect_alpaca_extended_history.py"),
        "--symbols", *symbols,
        "--start", start_day.isoformat(),
        "--end", local_day.isoformat(),
        "--feed", feed,
        "--output", str(raw_path),
    ])
    run_checked([
        sys.executable,
        str(SCRIPTS / "build_premarket_training_dataset_v2.py"),
        str(raw_path),
        "--output", str(dataset_path),
    ])
    run_checked([
        sys.executable,
        str(SCRIPTS / "train_premarket_directional_v5.py"),
        str(dataset_path),
        "--output", str(model_path),
    ])


def hybrid_from_payload(payload: dict) -> HybridModel:
    if tuple(payload.get("feature_names") or ()) != tuple(V5_FEATURE_NAMES):
        raise ValueError("V5 feature schema mismatch")
    return HybridModel(
        impute=np.asarray(payload["impute"], dtype=float),
        mean=np.asarray(payload["mean"], dtype=float),
        scale=np.asarray(payload["scale"], dtype=float),
        return_weights=np.asarray(payload["return_stage"]["weights"], dtype=float),
        return_bias=float(payload["return_stage"]["bias"]),
        direction_weights=np.asarray(payload["direction_stage"]["weights"], dtype=float),
        direction_bias=float(payload["direction_stage"]["bias"]),
        direction_temperature=float(payload["direction_stage"]["temperature"]),
    )


def load_models(model_path: Path) -> dict[str, HybridModel]:
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    if payload.get("model_version") != "premarket_directional_v5_hybrid_return":
        raise ValueError("Unexpected premarket v5 model artifact version")
    targets = payload.get("targets") or {}
    missing = [target for target in PREMARKET_TARGETS if target not in targets]
    if missing:
        raise ValueError(f"Model artifact missing targets: {', '.join(missing)}")
    return {target: hybrid_from_payload(targets[target]) for target in PREMARKET_TARGETS}


def prediction_for_symbol(*, ticker: str, raw: pd.DataFrame, as_of: datetime, models: dict[str, HybridModel]) -> dict:
    ticker_frame = raw.loc[raw["ticker"] == ticker].copy()
    if ticker_frame.empty:
        return {"ticker": ticker, "available": False, "reason": "no_market_data"}

    ticker_frame = ticker_frame.sort_values("timestamp").set_index("timestamp")
    local_dates = ticker_frame.index.tz_convert(NY).date
    day = as_of.astimezone(NY).date()
    history = ticker_frame.loc[local_dates <= day]
    prior_close = previous_regular_close(history, day)
    current = history.loc[history.index.tz_convert(NY).date == day]
    current = current.loc[(current.index.tz_convert(NY).time >= PREMARKET_START) & (current.index.tz_convert(NY).time < REGULAR_OPEN)]
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    observed = current.loc[current.index <= cutoff]
    if prior_close is None or len(observed) < 3:
        return {"ticker": ticker, "available": False, "reason": "insufficient_causal_bars_or_previous_close"}

    features = extract_predictive_features(observed, previous_close=prior_close, as_of=cutoff)
    local = as_of.astimezone(NY)
    minutes_to_open = (9 * 60 + 30) - (local.hour * 60 + local.minute)
    base = pd.Series({**features, "minutes_to_open": minutes_to_open})
    engineered = pd.DataFrame([engineer_row(base)])

    forecasts: dict[str, dict] = {}
    for target, model in models.items():
        horizon = int(target.removeprefix("premarket_").removesuffix("m"))
        sigma = horizon_sigma_pct(features, horizon)
        predicted_return, p_up = model.predict(engineered)
        predicted_return_pct = float(predicted_return[0])
        probability_up = float(p_up[0])
        confidence = max(probability_up, 1.0 - probability_up)
        regression_up = predicted_return_pct > 0
        classifier_up = probability_up >= 0.5
        agreement = regression_up == classifier_up
        normalized_move = abs(predicted_return_pct) / max(float(sigma or 0.0), 1e-9) if sigma else None
        actionable = bool(agreement and normalized_move is not None and normalized_move >= 0.20 and confidence >= 0.55)
        direction = "UP" if regression_up else "DOWN"
        forecasts[target] = {
            "direction": direction if actionable else "NO_TRADE",
            "raw_direction": direction,
            "predicted_return_pct": round(predicted_return_pct, 6),
            "probability_up": round(probability_up, 6),
            "probability_down": round(1.0 - probability_up, 6),
            "directional_confidence": round(confidence, 6),
            "expected_sigma_pct": None if sigma is None else round(float(sigma), 6),
            "normalized_predicted_move": None if normalized_move is None else round(float(normalized_move), 6),
            "model_agreement": bool(agreement),
            "actionable_shadow_signal": actionable,
        }

    return {
        "ticker": ticker,
        "available": True,
        "as_of_utc": as_of.isoformat(),
        "as_of_et": local.isoformat(),
        "last_observed_bar_utc": observed.index[-1].isoformat(),
        "previous_regular_close": round(float(prior_close), 6),
        "feature_count_present": int(sum(value is not None and pd.notna(value) for value in features.values())),
        "forecasts": forecasts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Orion Premarket v5 as a cloud-only shadow research job.")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--as-of", default=None, help="ISO timestamp; default is current UTC time")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--workdir", type=Path, default=Path("backend/data/cloud_shadow/premarket_v5"))
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/premarket_v5/latest_prediction.json"))
    parser.add_argument("--allow-outside-window", action="store_true", help="Testing/manual research only; do not use in the scheduled workflow")
    args = parser.parse_args()

    if args.lookback_days < 80:
        raise ValueError("--lookback-days must be at least 80 calendar days")
    symbols = parse_symbols(args.symbols)
    as_of = parse_as_of(args.as_of)
    active, reason, local = premarket_window_status(as_of)
    if not active and not args.allow_outside_window:
        print(json.dumps({"status": "skipped", "reason": reason, "as_of_et": local.isoformat()}))
        return 0

    workdir = args.workdir
    raw_path = workdir / "raw.csv"
    dataset_path = workdir / "training.csv"
    model_path = workdir / "premarket_v5_model.json"
    for path in (workdir, args.output.parent):
        path.mkdir(parents=True, exist_ok=True)

    collect_and_train(
        symbols=symbols,
        as_of=as_of,
        raw_path=raw_path,
        dataset_path=dataset_path,
        model_path=model_path,
        lookback_days=args.lookback_days,
        feed=args.feed,
    )

    raw = normalize_columns(pd.read_csv(raw_path))
    models = load_models(model_path)
    predictions = [prediction_for_symbol(ticker=symbol, raw=raw, as_of=as_of, models=models) for symbol in symbols]
    payload = {
        "runner_version": RUNNER_VERSION,
        "mode": "shadow_research_only",
        "order_submission_enabled": False,
        "as_of_utc": as_of.isoformat(),
        "as_of_et": local.isoformat(),
        "feed": args.feed,
        "symbols": symbols,
        "git_sha": os.getenv("GITHUB_SHA"),
        "raw_csv_sha256": file_sha256(raw_path),
        "training_csv_sha256": file_sha256(dataset_path),
        "model_artifact_sha256": file_sha256(model_path),
        "predictions": predictions,
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "output": str(args.output), "available": sum(bool(item.get("available")) for item in predictions), "symbols": len(symbols)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
