from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from run_sector_specialist_historical_evidence import (
    REPO_ROOT,
    _canonical_json_sha256,
    _frame_meta,
    _git_sha,
    _source_fingerprints,
)

CORE_FILES = (
    "backend/evals/benchmark_industry_specialist_v1.py",
    "backend/evals/industry_specialist_prereg_v1.json",
    "backend/evals/specialist_engine_tournament.py",
    "backend/evals/benchmark_intraday_challenger_v4.py",
    "backend/evals/intraday_challenger_tournament.py",
    "backend/app/services/intraday_probability_backtest_v3.py",
    "backend/app/services/intraday_probability_calibration_v3_1.py",
)
CONTRACT = "orion-industry-specialist-historical-evidence-v1"


def run_evidence(prereg_path: Path) -> dict[str, Any]:
    import yfinance as yf

    backend = REPO_ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from evals.benchmark_industry_specialist_v1 import load_prereg, run_real_data_screen

    prereg = load_prereg(prereg_path)
    required = {"SPY", *[str(x).upper() for x in prereg["industry_symbols"] + prereg["control_symbols"]]}
    original_download = yf.download
    downloads: list[dict[str, Any]] = []

    def captured_download(*args: Any, **kwargs: Any) -> Any:
        frame = original_download(*args, **kwargs)
        symbol = str(args[0] if args else kwargs.get("tickers") or "").strip().upper()
        meta = _frame_meta(frame)
        meta.update({"symbol": symbol, "period": kwargs.get("period"), "interval": kwargs.get("interval"), "prepost": kwargs.get("prepost")})
        downloads.append(meta)
        return frame

    yf.download = captured_download
    try:
        benchmark = run_real_data_screen(prereg)
    finally:
        yf.download = original_download

    captured = {str(row.get("symbol") or "") for row in downloads}
    missing = sorted(required - captured)
    if missing:
        raise RuntimeError("Industry-screen data provenance incomplete: " + ", ".join(missing))

    evidence = {
        "contract": CONTRACT,
        "research_only": True,
        "screening_only": True,
        "decisive_holdout": False,
        "promotion_authorized": False,
        "git_sha": _git_sha(REPO_ROOT),
        "candidate_id": prereg["candidate_id"],
        "market_data": {"provider": "yfinance", "captured_download_count": len(downloads), "downloads": downloads},
        "source_sha256": _source_fingerprints(REPO_ROOT, CORE_FILES),
        "benchmark_result_sha256": _canonical_json_sha256(benchmark),
    }
    payload = {"evidence": evidence, "benchmark": benchmark}
    evidence["evidence_payload_sha256"] = _canonical_json_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run preregistered semiconductor 3h historical screen with content-addressed evidence.")
    parser.add_argument("--prereg", type=Path, default=Path("backend/evals/industry_specialist_prereg_v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run_evidence(args.prereg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "candidate_id": payload["evidence"]["candidate_id"], "benchmark_result_sha256": payload["evidence"]["benchmark_result_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
