"""Deterministic symbol sharding for Orion cloud accelerated learning.

The cloud workflow processes one small shard per run so each replay finishes well
inside the hosted-runner timeout while the persistent SIMULATED_FORWARD database
accumulates evidence across runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

CLOUD_REPLAY_SYMBOLS: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "AMD", "NFLX", "ORCL", "CRM", "ADBE", "QCOM", "INTC",
    "MU", "AMAT", "LRCX", "KLAC", "TXN", "PANW", "PLTR", "UBER",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA",
    "XOM", "CVX", "COP", "SLB", "LLY", "UNH", "JNJ", "ABBV",
    "WMT", "COST", "HD", "LOW", "DIS", "BA", "CAT", "GE", "F", "GM",
)


@dataclass(frozen=True)
class CloudReplayShard:
    shard_index: int
    shard_count: int
    symbols: tuple[str, ...]


def select_cloud_replay_shard(
    run_number: int,
    *,
    shard_size: int = 10,
    symbols: Sequence[str] = CLOUD_REPLAY_SYMBOLS,
) -> CloudReplayShard:
    """Select a deterministic rotating shard for a GitHub Actions run number."""
    if run_number < 1:
        raise ValueError("run_number must be >= 1")
    if shard_size < 1:
        raise ValueError("shard_size must be >= 1")
    normalized = tuple(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip())
    if not normalized:
        raise ValueError("symbols must not be empty")

    shards = tuple(
        normalized[start : start + shard_size]
        for start in range(0, len(normalized), shard_size)
    )
    shard_index = (run_number - 1) % len(shards)
    return CloudReplayShard(
        shard_index=shard_index,
        shard_count=len(shards),
        symbols=shards[shard_index],
    )
