from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


HORIZON_RE = re.compile(r"^(?:premarket_)?(?P<value>\d+)(?P<unit>m|h)$")
EPS = 1e-12
MAX_BAR_STALENESS = timedelta(minutes=5)
TARGET_TOLERANCE = timedelta(minutes=5)
NY = ZoneInfo("America/New_York")


@dataclass
class ForecastRecord:
    source_file: str
    engine: str
    symbol: str
    horizon: str
    horizon_minutes: int
    prediction_time_utc: str
    target_time_utc: str
    probability_up: float
    predicted_direction: str
    actual_up: int
    base_price: float
    outcome_price: float
    realized_return_pct: float
    correct_direction: bool
    brier: float
    log_loss: float
    lineage: dict[str, Any]
    reliability_profile_source: str | None = None
    profile_validated_for_symbol: bool | None = None


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone: {value}")
    return dt.astimezone(timezone.utc)


def horizon_minutes(label: str) -> int:
    match = HORIZON_RE.match(str(label).strip())
    if not match:
        raise ValueError(f"Unsupported horizon: {label}")
    value = int(match.group("value"))
    if value <= 0:
        raise ValueError(f"Horizon must be positive: {label}")
    return value if match.group("unit") == "m" else value * 60


def normalize_probability(value: Any) -> float | None:
    if value is None:
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(p):
        return None
    if p > 1.0:
        p /= 100.0
    if not 0.0 <= p <= 1.0:
        return None
    return p


def premarket_regime(prediction_time_utc: str) -> str:
    """Map a timestamp to the pre-registered premarket sampling regimes.

    The boundaries mirror the dataset builder cadence: sparse early sampling
    before 07:00 ET, medium cadence from 07:00 through 08:59 ET, and dense late
    sampling from 09:00 until the 09:30 regular-session open.
    """
    local = parse_iso(prediction_time_utc).astimezone(NY)
    minute_of_day = local.hour * 60 + local.minute
    if minute_of_day < 7 * 60:
        return "early"
    if minute_of_day < 9 * 60:
        return "mid"
    return "late"


def load_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"ticker", "timestamp", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Bars CSV missing columns: {', '.join(sorted(missing))}")
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["ticker", "timestamp", "close"])
    return frame.sort_values(["ticker", "timestamp"]).reset_index(drop=True)


def _lineage_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("lineage"), dict):
        return dict(payload["lineage"])
    return {
        "git_sha": payload.get("git_sha"),
        "raw_csv_sha256": payload.get("raw_csv_sha256"),
        "training_csv_sha256": payload.get("training_csv_sha256"),
        "model_artifact_sha256": payload.get("model_artifact_sha256"),
    }


def _acquisition_provenance_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    provenance = payload.get("acquisition_provenance")
    return dict(provenance) if isinstance(provenance, dict) else None


def horizon_forward_eligible(
    forecast: dict[str, Any],
    *,
    target_time: datetime | None = None,
) -> bool:
    """Return whether an attested forecast still existed before its own target.

    Older historical/offline fixtures predate acquisition attestation and retain
    their previous evaluator behavior. Once acquisition provenance is present,
    however, the evaluator fails closed: the artifact must be globally marked
    forward-eligible and its prediction-producing collection must have completed
    strictly before the specific horizon target. This prevents delayed/recovery
    workflow runs from scoring outcomes that were already observable.
    """
    provenance = forecast.get("acquisition_provenance")
    if provenance is None:
        return True
    if not isinstance(provenance, dict) or provenance.get("forward_eligible") is not True:
        return False

    completed_at = provenance.get("collection_completed_at_utc")
    if not completed_at:
        return False
    try:
        completed = parse_iso(str(completed_at))
        if target_time is None:
            prediction_time = parse_iso(str(forecast["prediction_time"]))
            target_time = prediction_time + timedelta(minutes=horizon_minutes(str(forecast["horizon"])))
    except (KeyError, TypeError, ValueError):
        return False
    return completed < target_time


def iter_forecasts(payload: dict[str, Any], source_file: str) -> Iterable[dict[str, Any]]:
    lineage = _lineage_from_payload(payload)
    acquisition_provenance = _acquisition_provenance_from_payload(payload)

    if isinstance(payload.get("predictions"), list):
        for symbol_row in payload["predictions"]:
            if not isinstance(symbol_row, dict) or not symbol_row.get("available"):
                continue
            symbol = str(symbol_row.get("ticker") or "").upper().strip()
            as_of = symbol_row.get("as_of_utc") or payload.get("as_of_utc")
            for label, row in (symbol_row.get("forecasts") or {}).items():
                if not isinstance(row, dict):
                    continue
                p = normalize_probability(row.get("probability_up"))
                if p is None:
                    continue
                yield {
                    "source_file": source_file,
                    "engine": "premarket_v5",
                    "symbol": symbol,
                    "horizon": str(label),
                    "prediction_time": as_of,
                    "probability_up": p,
                    "direction": row.get("raw_direction") or row.get("direction"),
                    "lineage": lineage,
                    "acquisition_provenance": acquisition_provenance,
                    "reliability_profile_source": None,
                    "profile_validated_for_symbol": None,
                }

    results = payload.get("results")
    symbols = results.get("symbols") if isinstance(results, dict) else None
    if isinstance(symbols, dict):
        for symbol, symbol_row in symbols.items():
            if not isinstance(symbol_row, dict) or not symbol_row.get("available"):
                continue

            # Regular-hours evidence is scoreable only when the ensemble itself
            # proves that V1 and V2 used the exact same source cutoff. Artifact
            # creation time is operational metadata, not a market-data cutoff,
            # and must never be substituted for a missing/unaligned source time.
            if symbol_row.get("source_timestamp_aligned") is not True:
                continue
            as_of = symbol_row.get("as_of")
            if not as_of:
                continue
            try:
                parse_iso(str(as_of))
            except (TypeError, ValueError):
                continue

            for label, row in (symbol_row.get("horizons") or {}).items():
                if not isinstance(row, dict) or not row.get("available") or row.get("suppressed"):
                    continue
                p = normalize_probability(row.get("probability_up"))
                if p is None:
                    continue
                yield {
                    "source_file": source_file,
                    "engine": "regular_hours_v3_1",
                    "symbol": str(symbol).upper().strip(),
                    "horizon": str(label),
                    "prediction_time": as_of,
                    "probability_up": p,
                    "direction": row.get("direction"),
                    "lineage": lineage,
                    "acquisition_provenance": acquisition_provenance,
                    "reliability_profile_source": symbol_row.get("reliability_profile_source"),
                    "profile_validated_for_symbol": symbol_row.get("profile_validated_for_symbol"),
                }


def _price_at_or_before(frame: pd.DataFrame, moment: datetime) -> tuple[datetime, float] | None:
    stamp = pd.Timestamp(moment)
    eligible = frame.loc[frame["timestamp"] <= stamp]
    if eligible.empty:
        return None
    row = eligible.iloc[-1]
    observed = row["timestamp"].to_pydatetime()
    if moment - observed > MAX_BAR_STALENESS:
        return None
    return observed, float(row["close"])


def _price_at_or_after(frame: pd.DataFrame, moment: datetime) -> tuple[datetime, float] | None:
    stamp = pd.Timestamp(moment)
    eligible = frame.loc[frame["timestamp"] >= stamp]
    if eligible.empty:
        return None
    row = eligible.iloc[0]
    observed = row["timestamp"].to_pydatetime()
    if observed - moment > TARGET_TOLERANCE:
        return None
    return observed, float(row["close"])


def settle_forecast(forecast: dict[str, Any], bars: pd.DataFrame, cutoff: datetime) -> ForecastRecord | None:
    prediction_time = parse_iso(str(forecast["prediction_time"]))
    minutes = horizon_minutes(str(forecast["horizon"]))
    target_time = prediction_time + timedelta(minutes=minutes)
    if target_time > cutoff or not horizon_forward_eligible(forecast, target_time=target_time):
        return None

    symbol_bars = bars.loc[bars["ticker"] == forecast["symbol"]]
    if symbol_bars.empty:
        return None
    base = _price_at_or_before(symbol_bars, prediction_time)
    outcome = _price_at_or_after(symbol_bars, target_time)
    if base is None or outcome is None:
        return None

    _, base_price = base
    _, outcome_price = outcome
    if base_price <= 0:
        return None
    realized_return_pct = ((outcome_price / base_price) - 1.0) * 100.0
    actual_up = int(outcome_price > base_price)
    p = float(forecast["probability_up"])
    clipped = min(max(p, EPS), 1.0 - EPS)
    predicted_up = p >= 0.5

    return ForecastRecord(
        source_file=str(forecast["source_file"]),
        engine=str(forecast["engine"]),
        symbol=str(forecast["symbol"]),
        horizon=str(forecast["horizon"]),
        horizon_minutes=minutes,
        prediction_time_utc=prediction_time.isoformat(),
        target_time_utc=target_time.isoformat(),
        probability_up=p,
        predicted_direction=str(forecast.get("direction") or ("UP" if predicted_up else "DOWN")),
        actual_up=actual_up,
        base_price=round(base_price, 6),
        outcome_price=round(outcome_price, 6),
        realized_return_pct=round(realized_return_pct, 6),
        correct_direction=bool(predicted_up == bool(actual_up)),
        brier=(p - actual_up) ** 2,
        log_loss=-(actual_up * math.log(clipped) + (1 - actual_up) * math.log(1.0 - clipped)),
        lineage=dict(forecast.get("lineage") or {}),
        reliability_profile_source=forecast.get("reliability_profile_source"),
        profile_validated_for_symbol=forecast.get("profile_validated_for_symbol"),
    )


def expected_calibration_error(records: list[ForecastRecord], bins: int = 10) -> float | None:
    if not records:
        return None
    total = len(records)
    ece = 0.0
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        bucket = [r for r in records if low <= r.probability_up < high or (index == bins - 1 and r.probability_up == 1.0)]
        if not bucket:
            continue
        confidence = sum(r.probability_up for r in bucket) / len(bucket)
        frequency = sum(r.actual_up for r in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(confidence - frequency)
    return ece


def summarize(records: list[ForecastRecord], eligible_forecasts: int) -> dict[str, Any]:
    if not records:
        return {
            "settled": 0,
            "eligible_forecasts": eligible_forecasts,
            "coverage": 0.0 if eligible_forecasts else None,
            "brier_score": None,
            "log_loss": None,
            "directional_accuracy": None,
            "ece_10_bin": None,
        }
    n = len(records)
    return {
        "settled": n,
        "eligible_forecasts": eligible_forecasts,
        "coverage": round(n / eligible_forecasts, 6) if eligible_forecasts else None,
        "brier_score": round(sum(r.brier for r in records) / n, 8),
        "log_loss": round(sum(r.log_loss for r in records) / n, 8),
        "directional_accuracy": round(sum(r.correct_direction for r in records) / n, 6),
        "ece_10_bin": round(float(expected_calibration_error(records) or 0.0), 8),
    }


def grouped_summaries(records: list[ForecastRecord]) -> dict[str, Any]:
    groups: dict[str, list[ForecastRecord]] = {}
    for record in records:
        key = f"{record.engine}:{record.horizon}"
        groups.setdefault(key, []).append(record)
    return {key: summarize(rows, len(rows)) for key, rows in sorted(groups.items())}


def premarket_regime_summaries(records: list[ForecastRecord]) -> dict[str, Any]:
    """Return target-aware early/mid/late diagnostics for Premarket V5 only."""
    groups: dict[str, list[ForecastRecord]] = {}
    for record in records:
        if record.engine != "premarket_v5":
            continue
        regime = premarket_regime(record.prediction_time_utc)
        key = f"{regime}:{record.horizon}"
        groups.setdefault(key, []).append(record)
    return {key: summarize(rows, len(rows)) for key, rows in sorted(groups.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle immutable Orion cloud-shadow predictions against later observed bars.")
    parser.add_argument("predictions", nargs="+", type=Path, help="One or more cloud-shadow prediction JSON files")
    parser.add_argument("--bars", required=True, type=Path, help="1-minute bars CSV containing ticker,timestamp,close")
    parser.add_argument("--as-of", default=None, help="Evaluation cutoff timestamp with timezone; default current UTC")
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/evaluation/latest.json"))
    args = parser.parse_args()

    cutoff = parse_iso(args.as_of) if args.as_of else datetime.now(timezone.utc)
    bars = load_bars(args.bars)
    forecasts: list[dict[str, Any]] = []
    for path in args.predictions:
        payload = json.loads(path.read_text(encoding="utf-8"))
        forecasts.extend(iter_forecasts(payload, str(path)))

    mature = []
    settled: list[ForecastRecord] = []
    for forecast in forecasts:
        prediction_time = parse_iso(str(forecast["prediction_time"]))
        target_time = prediction_time + timedelta(minutes=horizon_minutes(str(forecast["horizon"])))
        if target_time <= cutoff and horizon_forward_eligible(forecast, target_time=target_time):
            mature.append(forecast)
            record = settle_forecast(forecast, bars, cutoff)
            if record is not None:
                settled.append(record)

    payload = {
        "contract": "orion-cloud-shadow-evaluation-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_cutoff_utc": cutoff.isoformat(),
        "leakage_safe": True,
        "policy": {
            "base_price": "latest bar at-or-before prediction timestamp, maximum 5 minutes stale",
            "outcome_price": "first bar at-or-after fully elapsed horizon, maximum 5 minutes late",
            "suppressed_regular_hours_probabilities": "excluded",
            "regular_hours_timestamp_provenance": "requires symbol-level as_of and source_timestamp_aligned=true; artifact created_at_utc is never a source-data cutoff fallback",
            "future_prediction_rows": "excluded until horizon fully elapses",
            "attested_forward_acquisition": "when acquisition provenance is present, forward_eligible must be true and collection must complete strictly before that horizon target; already-observable horizons are excluded rather than scored",
            "legacy_unattested_inputs": "retain historical/offline evaluator behavior for compatibility and are not proof of decision-grade forward acquisition",
            "premarket_regimes_et": "early <07:00; mid 07:00-08:59; late 09:00-09:29",
        },
        "summary": summarize(settled, len(mature)),
        "by_engine_horizon": grouped_summaries(settled),
        "by_premarket_regime_horizon": premarket_regime_summaries(settled),
        "records": [asdict(row) for row in settled],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
