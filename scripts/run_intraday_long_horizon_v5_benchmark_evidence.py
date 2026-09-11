from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_FILES = (
    "backend/evals/benchmark_intraday_long_horizon_v5.py",
    "backend/evals/long_horizon_challenger_gate.py",
    "backend/evals/intraday_challenger_tournament.py",
    "backend/evals/benchmark_intraday_challenger_v4.py",
    "backend/app/services/intraday_probability_backtest_v3.py",
    "backend/app/services/intraday_probability_long_horizon_challenger_v5.py",
    "backend/app/services/intraday_probability_calibration_v3_1.py",
)
CONTRACT = "orion-long-horizon-v5-benchmark-evidence-v1"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(encoded)


def _frame_meta(frame: Any) -> dict[str, Any]:
    csv = frame.to_csv(index=True, lineterminator="\n")
    index = getattr(frame, "index", None)
    rows = int(len(frame))
    return {
        "sha256": _sha256_bytes(csv.encode("utf-8")),
        "rows": rows,
        "first_index": str(index[0]) if rows and index is not None else None,
        "last_index": str(index[-1]) if rows and index is not None else None,
    }


def _git_sha(repo_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _source_fingerprints(repo_root: Path, paths: Iterable[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for relative in paths:
        path = repo_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Required benchmark source missing: {relative}")
        output[relative] = _sha256_bytes(path.read_bytes())
    return output


def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            output.append(symbol)
    if not output:
        raise ValueError("At least one symbol is required")
    return output


def run_evidence(
    symbols: Sequence[str],
    *,
    period: str = "60d",
    interval: str = "5m",
    calibration_fraction: float = 0.60,
    min_symbols_per_horizon: int = 3,
    min_observations: int = 80,
    min_sessions: int = 8,
    bootstrap_samples: int = 2000,
    repo_root: Path = REPO_ROOT,
    source_paths: Sequence[str] = CORE_FILES,
    yf_module: Any | None = None,
    benchmark_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if yf_module is None:
        import yfinance as yf_module  # type: ignore
    if benchmark_fn is None:
        backend = repo_root / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from evals.benchmark_intraday_long_horizon_v5 import benchmark_symbols as benchmark_fn

    normalized = _normalize_symbols(symbols)
    original_download = yf_module.download
    downloads: list[dict[str, Any]] = []

    def captured_download(*args: Any, **kwargs: Any) -> Any:
        frame = original_download(*args, **kwargs)
        symbol = str(args[0] if args else kwargs.get("tickers") or "").strip().upper()
        meta = _frame_meta(frame)
        meta.update({
            "symbol": symbol,
            "period": kwargs.get("period"),
            "interval": kwargs.get("interval"),
            "auto_adjust": kwargs.get("auto_adjust"),
            "prepost": kwargs.get("prepost"),
        })
        downloads.append(meta)
        return frame

    yf_module.download = captured_download
    try:
        result = benchmark_fn(
            normalized,
            period=period,
            interval=interval,
            calibration_fraction=calibration_fraction,
            min_symbols_per_horizon=min_symbols_per_horizon,
            min_observations=min_observations,
            min_sessions=min_sessions,
            bootstrap_samples=bootstrap_samples,
        )
    finally:
        yf_module.download = original_download

    captured = {row["symbol"] for row in downloads if row.get("symbol")}
    missing = sorted((set(normalized) | {"SPY"}) - captured)
    if missing:
        raise RuntimeError(f"Benchmark data provenance incomplete; missing captured downloads for: {', '.join(missing)}")

    evidence = {
        "contract": CONTRACT,
        "research_only": True,
        "historical_screening_only": True,
        "forward_research_eligible": False,
        "runtime_modified": False,
        "promotion_allowed": False,
        "git_sha": _git_sha(repo_root),
        "python": {"implementation": platform.python_implementation(), "version": platform.python_version()},
        "parameters": {
            "symbols": normalized,
            "period": period,
            "interval": interval,
            "calibration_fraction": calibration_fraction,
            "min_symbols_per_horizon": min_symbols_per_horizon,
            "min_observations": min_observations,
            "min_sessions": min_sessions,
            "bootstrap_samples": bootstrap_samples,
        },
        "market_data": {"provider": "yfinance", "captured_download_count": len(downloads), "downloads": downloads},
        "source_sha256": _source_fingerprints(repo_root, source_paths),
        "benchmark_result_sha256": _canonical_json_sha256(result),
        "benchmark_research_conclusion": result.get("research_conclusion"),
        "candidate_design_id": result.get("candidate_design_id"),
    }
    payload = {"evidence": evidence, "benchmark": result}
    evidence["evidence_payload_sha256"] = _canonical_json_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen Orion long-horizon V5 historical screen with data/code provenance.")
    parser.add_argument("symbols", nargs="*", default=["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ"])
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--calibration-fraction", type=float, default=0.60)
    parser.add_argument("--min-symbols-per-horizon", type=int, default=3)
    parser.add_argument("--min-observations", type=int, default=80)
    parser.add_argument("--min-sessions", type=int, default=8)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = run_evidence(
        args.symbols,
        period=args.period,
        interval=args.interval,
        calibration_fraction=args.calibration_fraction,
        min_symbols_per_horizon=args.min_symbols_per_horizon,
        min_observations=args.min_observations,
        min_sessions=args.min_sessions,
        bootstrap_samples=args.bootstrap_samples,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "benchmark_result_sha256": payload["evidence"]["benchmark_result_sha256"],
        "research_conclusion": payload["evidence"]["benchmark_research_conclusion"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
