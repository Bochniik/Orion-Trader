from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.intraday_probability_long_horizon_challenger_v5 import DESIGN_ID
from app.services.intraday_probability_long_horizon_v5_forward import estimate_long_horizon_v5
from app.services.intraday_probability_runtime_v3_1 import estimate_intraday_probabilities_v3_1

NY = ZoneInfo("America/New_York")
CONTRACT = "orion-long-horizon-v5-paired-shadow-v1"
RUNNER_VERSION = "long-horizon-v5-paired-shadow-v2"
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")
WINDOW_OPEN = time(10, 0)
WINDOW_CLOSE = time(13, 30)
REGULAR_CLOSE = time(16, 0)
HORIZON_HOURS = {"3h": 3, "5h": 5}
LINEAGE_FILES = (
    "scripts/run_long_horizon_v5_paired_cloud_shadow.py",
    "backend/app/services/intraday_probability_long_horizon_v5_forward.py",
    "backend/app/services/intraday_probability_long_horizon_challenger_v5.py",
    "backend/app/services/intraday_probability_runtime_v3_1.py",
    "backend/app/services/intraday_probability_ensemble_engine.py",
)


def parse_symbols(values: Iterable[str]) -> list[str]:
    symbols: list[str] = []
    for value in values:
        for raw in str(value).replace(",", " ").split():
            symbol = raw.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    if not symbols:
        raise ValueError("At least one symbol is required")
    return symbols


def _settleable_horizons(local: datetime) -> list[str]:
    clock = local.time().replace(tzinfo=None)
    if local.weekday() >= 5 or not (WINDOW_OPEN <= clock <= WINDOW_CLOSE):
        return []
    eligible: list[str] = []
    for horizon, hours in HORIZON_HOURS.items():
        target = local + timedelta(hours=hours)
        if target.date() != local.date():
            continue
        if target.time().replace(tzinfo=None) <= REGULAR_CLOSE:
            eligible.append(horizon)
    return eligible


def session_gate(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(NY)
    clock = local.time().replace(tzinfo=None)
    in_collection_window = local.weekday() < 5 and WINDOW_OPEN <= clock <= WINDOW_CLOSE
    eligible_horizons = _settleable_horizons(local) if in_collection_window else []
    if not in_collection_window:
        reason = "outside_long_horizon_shadow_window"
    elif not eligible_horizons:
        reason = "no_settleable_horizon_before_regular_close"
    else:
        reason = None
    return {
        "allowed": bool(eligible_horizons),
        "as_of_et": local.isoformat(),
        "window_et": "10:00-13:30",
        "regular_close_et": "16:00",
        "eligible_horizons": eligible_horizons,
        "reason": reason,
    }


def _canonical_timestamp(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return result.stdout.strip() or None


def lineage() -> dict[str, Any]:
    return {
        "git_commit": _git_commit(),
        "design_id": DESIGN_ID,
        "files_sha256": {name: _sha256(ROOT / name) for name in LINEAGE_FILES},
    }


def _incumbent_probability(row: dict[str, Any]) -> float | None:
    raw = row.get("probability_up")
    if raw is None:
        raw = row.get("suppressed_probability_up")
    if raw is None:
        return None
    value = float(raw)
    return value / 100.0 if value > 1.0 else value


def run_symbol(symbol: str, expected_horizons: Iterable[str] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    horizons = tuple(expected_horizons or HORIZON_HOURS)
    unknown = sorted(set(horizons) - set(HORIZON_HOURS))
    if unknown:
        return [], f"unknown_expected_horizons:{','.join(unknown)}"
    try:
        challenger = estimate_long_horizon_v5(symbol)
        incumbent = estimate_intraday_probabilities_v3_1(symbol)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"

    challenger_time = _canonical_timestamp(challenger.get("as_of"))
    incumbent_time = _canonical_timestamp(incumbent.get("as_of"))
    if not challenger_time:
        return [], "challenger_missing_prediction_time"
    if not incumbent_time:
        return [], "incumbent_source_timestamp_unaligned_or_missing"
    if challenger_time != incumbent_time:
        return [], f"paired_timestamp_mismatch:{incumbent_time}!={challenger_time}"

    rows: list[dict[str, Any]] = []
    challenger_horizons = challenger.get("horizons") or {}
    incumbent_horizons = incumbent.get("horizons") or {}
    for horizon in horizons:
        c_row = challenger_horizons.get(horizon) or {}
        i_row = incumbent_horizons.get(horizon) or {}
        if not c_row.get("available"):
            continue
        c_probability = c_row.get("probability_up")
        i_probability = _incumbent_probability(i_row)
        if c_probability is None or i_probability is None:
            continue
        rows.append({
            "symbol": symbol,
            "horizon": horizon,
            "prediction_time_utc": challenger_time,
            "target_time_utc": c_row.get("target_time_utc"),
            "timestamp_pair_verified": True,
            "incumbent": {
                "engine": "regular_hours_v3_1",
                "probability_up": round(float(i_probability), 6),
                "direction": i_row.get("direction"),
                "was_runtime_suppressed": bool(i_row.get("suppressed", False)),
            },
            "challenger": {
                "engine": DESIGN_ID,
                "probability_up": round(float(c_probability), 6),
                "direction": c_row.get("direction"),
                "training_samples": c_row.get("training_samples"),
                "training_cutoff": c_row.get("training_cutoff"),
                "max_training_timestamp": c_row.get("max_training_timestamp"),
            },
        })
    return rows, None


def _coverage(symbols: list[str], horizons: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = {(str(row.get("symbol")), str(row.get("horizon"))) for row in rows}
    expected = {(symbol, horizon) for symbol in symbols for horizon in horizons}
    missing = sorted(expected - observed)
    return {
        "score_blind": True,
        "expected_pair_count": len(expected),
        "observed_pair_count": len(observed & expected),
        "complete": not missing,
        "missing_pairs": [{"symbol": symbol, "horizon": horizon} for symbol, horizon in missing],
    }


def build_payload(symbols: list[str], now: datetime | None = None) -> dict[str, Any]:
    gate = session_gate(now)
    payload: dict[str, Any] = {
        "contract": CONTRACT,
        "runner_version": RUNNER_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_gate": gate,
        "symbols_requested": symbols,
        "research_only": True,
        "order_submission_enabled": False,
        "runtime_modified": False,
        "promotion_allowed": False,
        "lineage": lineage(),
        "paired_predictions": [],
        "failures": {},
    }
    if not gate["allowed"]:
        payload["status"] = "skipped"
        payload["coverage"] = _coverage(symbols, [], [])
        return payload

    eligible_horizons = list(gate["eligible_horizons"])
    for symbol in symbols:
        rows, error = run_symbol(symbol, eligible_horizons)
        payload["paired_predictions"].extend(rows)
        if error:
            payload["failures"][symbol] = error

    coverage = _coverage(symbols, eligible_horizons, payload["paired_predictions"])
    for missing in coverage["missing_pairs"]:
        symbol = missing["symbol"]
        if symbol not in payload["failures"]:
            missing_for_symbol = [
                row["horizon"] for row in coverage["missing_pairs"] if row["symbol"] == symbol
            ]
            payload["failures"][symbol] = f"missing_expected_horizons:{','.join(missing_for_symbol)}"

    payload["coverage"] = coverage
    payload["status"] = "completed" if coverage["complete"] else "degraded"
    payload["paired_prediction_count"] = len(payload["paired_predictions"])
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect atomic paired V3.1/V5 long-horizon research predictions.")
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/long_horizon_v5/prediction.json"))
    args = parser.parse_args()
    payload = build_payload(parse_symbols(args.symbols))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "paired_prediction_count": len(payload["paired_predictions"]),
        "eligible_horizons": payload["session_gate"].get("eligible_horizons", []),
        "coverage_complete": payload.get("coverage", {}).get("complete"),
        "failures": len(payload["failures"]),
    }, sort_keys=True))
    if payload["status"] == "skipped":
        return 0
    return 0 if payload["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
