from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
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

from app.services.intraday_probability_runtime_v3_1 import (
    estimate_intraday_probabilities_v3_1,
)


NY = ZoneInfo("America/New_York")
RUNNER_VERSION = "regular-hours-v3-1-cloud-shadow-v1"
REGULAR_OPEN = time(9, 30)
LAST_PREDICTION_CUTOFF = time(15, 30)
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")
LINEAGE_FILES = (
    "scripts/run_regular_hours_v3_1_cloud_shadow.py",
    "backend/app/services/intraday_probability_runtime_v3_1.py",
    "backend/app/services/intraday_probability_ensemble_engine.py",
    "backend/app/services/intraday_probability_calibration_v3_1.py",
    "backend/app/services/intraday_probability_statistical_engine.py",
    "backend/requirements.txt",
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


def _now_et(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(NY)


def regular_hours_gate(now: datetime | None = None) -> dict[str, Any]:
    local = _now_et(now)
    weekday = local.weekday()
    clock = local.time().replace(tzinfo=None)
    is_weekday = weekday < 5
    in_window = is_weekday and REGULAR_OPEN <= clock <= LAST_PREDICTION_CUTOFF
    return {
        "allowed": in_window,
        "as_of_et": local.isoformat(),
        "weekday": weekday,
        "window_et": "09:30-15:30",
        "reason": None if in_window else "outside_regular_hours_shadow_window",
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return value or None


def lineage() -> dict[str, Any]:
    files: dict[str, str | None] = {}
    for relative in LINEAGE_FILES:
        path = ROOT / relative
        files[relative] = file_sha256(path) if path.exists() else None
    return {
        "git_commit": git_commit(),
        "files_sha256": files,
    }


def summarize_symbol(symbol: str, result: dict[str, Any]) -> dict[str, Any]:
    horizons: dict[str, Any] = {}
    for horizon, row in (result.get("horizons") or {}).items():
        if not isinstance(row, dict):
            continue
        horizons[horizon] = {
            "available": bool(row.get("available")),
            "direction": row.get("direction"),
            "probability_up": row.get("probability_up"),
            "probability_down": row.get("probability_down"),
            "directional_confidence": row.get("directional_confidence"),
            "display_policy": row.get("display_policy"),
            "suppressed": bool(row.get("suppressed", False)),
            "profile_validated_for_symbol": bool(row.get("profile_validated_for_symbol", False)),
            "reason": row.get("reason"),
        }

    return {
        "symbol": symbol,
        "available": bool(result.get("available")),
        "as_of": result.get("as_of"),
        "source_timestamp_aligned": bool(result.get("source_timestamp_aligned", False)),
        "source_as_of": dict(result.get("source_as_of") or {}),
        "engine_version": result.get("engine_version"),
        "cross_horizon_consensus": result.get("cross_horizon_consensus"),
        "reliability_profile_source": result.get("reliability_profile_source"),
        "profile_validated_for_symbol": bool(result.get("profile_validated_for_symbol", False)),
        "warnings": list(result.get("warnings") or []),
        "horizons": horizons,
    }


def run_shadow(symbols: list[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    failures: dict[str, str] = {}

    for symbol in symbols:
        try:
            raw = estimate_intraday_probabilities_v3_1(symbol)
            results[symbol] = summarize_symbol(symbol, raw)
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"

    available_symbols = sum(bool(row.get("available")) for row in results.values())
    return {
        "symbol_count": len(symbols),
        "available_symbol_count": available_symbols,
        "failure_count": len(failures),
        "symbols": results,
        "failures": failures,
    }


def build_payload(symbols: list[str], now: datetime | None = None) -> dict[str, Any]:
    gate = regular_hours_gate(now)
    payload: dict[str, Any] = {
        "contract": "orion-regular-hours-cloud-shadow-v1",
        "runner_version": RUNNER_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_gate": gate,
        "symbols_requested": symbols,
        "research_only": True,
        "order_submission_enabled": False,
        "runtime_modified": False,
        "lineage": lineage(),
    }
    if not gate["allowed"]:
        payload["status"] = "skipped"
        payload["reason"] = gate["reason"]
        payload["results"] = {}
        return payload

    payload["status"] = "completed"
    payload["results"] = run_shadow(symbols)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Orion regular-hours V3.1 predictions in cloud shadow/research mode."
    )
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/cloud_shadow/regular_hours_v3_1/prediction.json"),
    )
    parser.add_argument(
        "--allow-outside-session",
        action="store_true",
        help="Manual research override. Scheduled workflow should never use this flag.",
    )
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    payload = build_payload(symbols)
    if args.allow_outside_session and payload.get("status") == "skipped":
        payload["session_gate"]["manual_override"] = True
        payload["status"] = "completed_manual_override"
        payload["reason"] = None
        payload["results"] = run_shadow(symbols)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))

    if payload.get("status") == "skipped":
        return 0
    results = payload.get("results") or {}
    if int(results.get("available_symbol_count") or 0) == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())