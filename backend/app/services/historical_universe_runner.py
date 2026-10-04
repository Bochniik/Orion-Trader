"""Historical universe runner for accelerated SIMULATED_FORWARD learning.

Loads real historical OHLCV through an injectable provider, batches symbols through
PredictionArena, and records deterministic progress/checkpoint metadata without ever
writing into Orion's LIVE_FORWARD persistence path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
import uuid

import pandas as pd

from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.prediction_arena import PredictionArena

RUNNER_ID = "historical-universe-runner-v1"
HistoricalLoader = Callable[..., pd.DataFrame]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    return sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})


def _validate_history(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{symbol}: empty historical frame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError(f"{symbol}: historical frame must use DatetimeIndex")
    result = frame.copy()
    if result.index.tz is None:
        result.index = result.index.tz_localize("UTC")
    else:
        result.index = result.index.tz_convert("UTC")
    if result.index.has_duplicates:
        raise ValueError(f"{symbol}: duplicate timestamps")
    if not result.index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: timestamps must be monotonically increasing")
    return result


def yfinance_historical_loader(
    symbol: str,
    *,
    period: str,
    interval: str,
    prepost: bool = False,
) -> pd.DataFrame:
    """Default real-market loader. Network access is isolated behind this function."""
    import yfinance as yf

    return yf.download(
        str(symbol).strip().upper(),
        period=period,
        interval=interval,
        auto_adjust=False,
        prepost=bool(prepost),
        progress=False,
        threads=False,
    )


@dataclass(frozen=True)
class UniverseRunnerConfig:
    period: str = "60d"
    interval: str = "5m"
    benchmark_symbol: str = "SPY"
    batch_size: int = 10
    prepost: bool = False
    continue_on_symbol_error: bool = True
    resume_from_checkpoint: bool = True

    def __post_init__(self) -> None:
        if int(self.batch_size) < 1:
            raise ValueError("batch_size must be >= 1")
        if not str(self.period).strip():
            raise ValueError("period is required")
        if not str(self.interval).strip():
            raise ValueError("interval is required")
        if not str(self.benchmark_symbol).strip():
            raise ValueError("benchmark_symbol is required")


class HistoricalUniverseRunner:
    """Batch a symbol universe through PredictionArena using real historical data."""

    def __init__(
        self,
        *,
        arena: PredictionArena,
        loader: HistoricalLoader = yfinance_historical_loader,
        config: UniverseRunnerConfig | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        self.arena = arena
        self.loader = loader
        self.config = config or UniverseRunnerConfig()
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else None

    def _load(self, symbol: str) -> pd.DataFrame:
        frame = self.loader(
            symbol,
            period=self.config.period,
            interval=self.config.interval,
            prepost=self.config.prepost,
        )
        return _validate_history(frame, symbol=symbol)

    def _checkpoint_signature(self) -> dict[str, Any]:
        return {
            "runner_id": RUNNER_ID,
            "scope": SIMULATED_FORWARD,
            "period": self.config.period,
            "interval": self.config.interval,
            "prepost": self.config.prepost,
            "benchmark_symbol": self.config.benchmark_symbol.strip().upper(),
        }

    def _read_checkpoint(self) -> dict[str, Any] | None:
        if not self.config.resume_from_checkpoint or self.checkpoint_path is None or not self.checkpoint_path.exists():
            return None
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid replay checkpoint: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("invalid replay checkpoint: expected JSON object")
        expected = self._checkpoint_signature()
        mismatches = [key for key, value in expected.items() if payload.get(key) != value]
        if mismatches:
            raise ValueError(f"replay checkpoint configuration mismatch: {', '.join(mismatches)}")
        return payload

    def _write_checkpoint(self, payload: Mapping[str, Any]) -> None:
        if self.checkpoint_path is None:
            return
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        temp.write_text(json.dumps(dict(payload), default=str, sort_keys=True, indent=2), encoding="utf-8")
        temp.replace(self.checkpoint_path)

    def run(
        self,
        symbols: Iterable[str],
        *,
        run_id: str | None = None,
        decision_times_by_symbol: Mapping[str, Iterable[Any]] | None = None,
    ) -> dict[str, Any]:
        requested_symbols = _normalize_symbols(symbols)
        if not requested_symbols:
            raise ValueError("symbols must contain at least one valid ticker")

        benchmark_symbol = self.config.benchmark_symbol.strip().upper()
        run_id = str(run_id or uuid.uuid4())
        checkpoint = self._read_checkpoint()
        resumed_symbols = sorted(set(checkpoint.get("completed_symbols") or [])) if checkpoint else []
        resumed_symbol_set = set(resumed_symbols)
        universe_symbols = [symbol for symbol in requested_symbols if symbol not in resumed_symbol_set]

        batches: list[dict[str, Any]] = []
        symbol_failures: list[dict[str, str]] = list(checkpoint.get("failures") or []) if checkpoint else []
        successful_symbols: list[str] = list(resumed_symbols)
        total_predictions = int(checkpoint.get("prediction_count") or 0) if checkpoint else 0
        total_settled = int(checkpoint.get("settled_prediction_count") or 0) if checkpoint else 0
        weighted_brier_numerator = float(checkpoint.get("brier_numerator") or 0.0) if checkpoint else 0.0
        weighted_brier_count = int(checkpoint.get("brier_count") or 0) if checkpoint else 0
        weighted_direction_numerator = float(checkpoint.get("direction_numerator") or 0.0) if checkpoint else 0.0
        weighted_direction_count = int(checkpoint.get("direction_count") or 0) if checkpoint else 0

        benchmark = self._load(benchmark_symbol) if universe_symbols else None

        for offset in range(0, len(universe_symbols), self.config.batch_size):
            batch_symbols = universe_symbols[offset : offset + self.config.batch_size]
            frames: dict[str, pd.DataFrame] = {}
            for symbol in batch_symbols:
                if symbol == benchmark_symbol:
                    frames[symbol] = benchmark
                    continue
                try:
                    frames[symbol] = self._load(symbol)
                except Exception as exc:
                    if not self.config.continue_on_symbol_error:
                        raise
                    symbol_failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

            if not frames:
                self._write_checkpoint({
                    **self._checkpoint_signature(),
                    "run_id": run_id,
                    "completed_symbols": sorted(set(successful_symbols)),
                    "failures": symbol_failures,
                    "prediction_count": total_predictions,
                    "settled_prediction_count": total_settled,
                    "brier_numerator": weighted_brier_numerator,
                    "brier_count": weighted_brier_count,
                    "direction_numerator": weighted_direction_numerator,
                    "direction_count": weighted_direction_count,
                    "updated_at": _utc_now(),
                })
                continue

            batch_id = f"{run_id}:batch-{offset // self.config.batch_size + 1}"
            batch_decisions = None
            if decision_times_by_symbol is not None:
                batch_decisions = {
                    symbol: decision_times_by_symbol[symbol]
                    for symbol in frames
                    if symbol in decision_times_by_symbol
                }

            summary = self.arena.run(
                frames,
                benchmark,
                decision_times_by_symbol=batch_decisions,
                session_id=batch_id,
            )
            if summary.get("scope") != SIMULATED_FORWARD:
                raise RuntimeError("PredictionArena returned non-simulated evidence")

            batches.append({
                "session_id": batch_id,
                "symbols": sorted(frames),
                "prediction_count": int(summary.get("prediction_count") or 0),
                "settled_prediction_count": int(summary.get("settled_prediction_count") or 0),
                "failed_symbol_count": int(summary.get("failed_symbol_count") or 0),
                "horizons": summary.get("horizons") or {},
            })
            successful_symbols.extend(sorted((summary.get("symbols") or {}).keys()))
            total_predictions += int(summary.get("prediction_count") or 0)
            total_settled += int(summary.get("settled_prediction_count") or 0)

            for horizon in (summary.get("horizons") or {}).values():
                settled_count = int(horizon.get("settled_count") or 0)
                brier = horizon.get("mean_brier_up")
                if brier is not None and settled_count:
                    weighted_brier_numerator += float(brier) * settled_count
                    weighted_brier_count += settled_count
                accuracy = horizon.get("directional_accuracy")
                if accuracy is not None and settled_count:
                    weighted_direction_numerator += float(accuracy) * settled_count
                    weighted_direction_count += settled_count

            self._write_checkpoint({
                **self._checkpoint_signature(),
                "run_id": run_id,
                "completed_symbols": sorted(set(successful_symbols)),
                "failures": symbol_failures,
                "batch_count": int(checkpoint.get("batch_count") or 0) + len(batches) if checkpoint else len(batches),
                "prediction_count": total_predictions,
                "settled_prediction_count": total_settled,
                "brier_numerator": weighted_brier_numerator,
                "brier_count": weighted_brier_count,
                "direction_numerator": weighted_direction_numerator,
                "direction_count": weighted_direction_count,
                "updated_at": _utc_now(),
            })

        return {
            "runner_id": RUNNER_ID,
            "scope": SIMULATED_FORWARD,
            "run_id": run_id,
            "period": self.config.period,
            "interval": self.config.interval,
            "prepost": self.config.prepost,
            "benchmark_symbol": benchmark_symbol,
            "requested_symbol_count": len(requested_symbols),
            "resumed_symbol_count": len([symbol for symbol in requested_symbols if symbol in resumed_symbol_set]),
            "processed_symbol_count": len(universe_symbols),
            "successful_symbol_count": len(set(successful_symbols)),
            "failed_symbol_count": len(symbol_failures),
            "prediction_count": total_predictions,
            "settled_prediction_count": total_settled,
            "mean_brier_up": (
                weighted_brier_numerator / weighted_brier_count if weighted_brier_count else None
            ),
            "directional_accuracy": (
                weighted_direction_numerator / weighted_direction_count if weighted_direction_count else None
            ),
            "batches": batches,
            "failures": symbol_failures,
            "live_forward_mutated": False,
        }
