"""Read-only JPM SIMULATED_FORWARD evidence capacity preflight.

This is NOT an untouched lockbox certification or a benchmark.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

MODEL_VERSION = "long-horizon-v5-20260911-a"
HORIZONS = ("3h", "5h")
REQUIRED_COLUMNS = {
    "scope", "symbol", "horizon", "model_version", "prediction_time_utc",
    "target_time_utc", "settled_at_utc", "status", "actual_direction",
}


def inventory(database: Path, *, symbol: str = "JPM", model_version: str = MODEL_VERSION,
              lockbox_sessions: int = 100, min_development_sessions: int = 15) -> dict:
    if not symbol.isascii() or not symbol.isalnum() or not symbol.isupper():
        raise ValueError("symbol must be an uppercase alphanumeric ticker")
    if lockbox_sessions < 10 or min_development_sessions < 1:
        raise ValueError("invalid preregistration session configuration")
    report = {
        "contract": "orion-jpm-evidence-inventory-v3", "scope": "SIMULATED_FORWARD",
        "symbol": symbol, "model_version": model_version,
        "database_available": False, "provider_validated": False,
        "research_only": True, "live_forward_mutated": False,
        "automatic_live_promotion": False, "lockbox_reserved": False,
        "benchmark_performed": False, "verdict": "AWAITING_MORE_EVIDENCE",
        "horizons": {},
    }
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        report["reason"] = "simulated_forward_db_missing"
        return report
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(simulated_forward_predictions)")}
            if not REQUIRED_COLUMNS.issubset(columns):
                report["reason"] = "simulated_forward_schema_missing_required_columns"
                return report
            report["database_available"] = True
            report["settled_versions"] = {
                str(version): int(count)
                for version, count in connection.execute(
                    """SELECT model_version, COUNT(*) FROM simulated_forward_predictions
                       WHERE scope='SIMULATED_FORWARD' AND symbol=? AND status='settled'
                       GROUP BY model_version ORDER BY model_version""", (symbol,)
                ).fetchall()
            }
            for horizon in HORIZONS:
                rows = connection.execute(
                    """SELECT substr(prediction_time_utc, 1, 10) AS session,
                              COUNT(*) AS raw_count,
                              COUNT(DISTINCT prediction_time_utc) AS unique_count
                       FROM simulated_forward_predictions
                       WHERE scope = 'SIMULATED_FORWARD'
                         AND status = 'settled'
                         AND UPPER(COALESCE(actual_direction, '')) IN
                             ('UP','DOWN','BULLISH','BEARISH')
                         AND symbol = ? AND model_version = ? AND horizon = ?
                         AND julianday(target_time_utc) > julianday(prediction_time_utc)
                         AND julianday(settled_at_utc) >= julianday(target_time_utc)
                       GROUP BY substr(prediction_time_utc, 1, 10)
                       ORDER BY session""", (symbol, model_version, horizon)
                ).fetchall()
                distinct = [(str(session), int(unique)) for session, _, unique in rows if session]
                raw_count = sum(int(raw) for _, raw, _ in rows)
                sample_count = sum(count for _, count in distinct)
                candidate = distinct[-lockbox_sessions:]
                candidate_samples = sum(count for _, count in candidate)
                eligible = len(distinct) >= min_development_sessions + lockbox_sessions
                report["horizons"][horizon] = {
                    "settled_sessions": len(distinct),
                    "settled_unique_samples": sample_count,
                    "duplicate_rows": raw_count - sample_count,
                    "candidate_lockbox_sessions": len(candidate),
                    "candidate_lockbox_samples": candidate_samples,
                    "candidate_preregistration_ready": bool(
                        eligible and candidate_samples >= 1000 and raw_count == sample_count
                    ),
                    "development_sessions": None, "development_samples": None,
                    "untouched_lockbox_sessions": None, "untouched_lockbox_samples": None,
                    "accuracy": None, "brier": None, "ece": None, "coverage": None,
                    "session_stability": None, "uncertainty": None,
                }
            report["reason"] = "inventory_only_no_immutable_lockbox_or_benchmark"
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        report["reason"] = "simulated_forward_database_unreadable"
        report["database_available"] = False
        report["horizons"] = {}
        report["error_type"] = type(exc).__name__
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only settled JPM evidence inventory")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--symbol", default="JPM")
    args = parser.parse_args()
    result = inventory(Path(args.database), symbol=args.symbol)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
