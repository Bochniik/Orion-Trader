"""Liquidity-driven symbol selection for accelerated historical replay.

The selector reuses Orion's persistent market catalogue and existing liquidity
metrics. It ranks active, tradable US equities by 20-session average dollar
volume and returns only symbols that meet the configured evidence/liquidity gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from app.services.liquidity_engine import historical_liquidity_metrics
from app.services.market_universe_db import MarketUniverseDatabase

HistoryLoader = Callable[..., pd.DataFrame]


def yfinance_daily_history_loader(symbol: str, *, period: str = "1mo") -> pd.DataFrame:
    import yfinance as yf

    history = yf.download(
        str(symbol).strip().upper(),
        period=period,
        interval="1d",
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    # yfinance 1.x returns MultiIndex columns even for a single ticker.
    # Orion's liquidity engine consumes the provider-neutral OHLCV shape.
    if isinstance(history.columns, pd.MultiIndex):
        history = history.copy()
        history.columns = history.columns.get_level_values(0)
    return history


@dataclass(frozen=True)
class ReplayUniverseSelectionConfig:
    top_n: int = 100
    candidate_limit: int = 1000
    minimum_average_dollar_volume: float = 25_000_000.0
    minimum_history_sessions: int = 10
    history_period: str = "1mo"

    def __post_init__(self) -> None:
        if int(self.top_n) < 1:
            raise ValueError("top_n must be >= 1")
        if int(self.candidate_limit) < int(self.top_n):
            raise ValueError("candidate_limit must be >= top_n")
        if float(self.minimum_average_dollar_volume) < 0:
            raise ValueError("minimum_average_dollar_volume must be >= 0")
        if int(self.minimum_history_sessions) < 1:
            raise ValueError("minimum_history_sessions must be >= 1")


class ReplayLiquidityUniverseSelector:
    """Select replay symbols from Orion's tradable US-equity catalogue."""

    def __init__(
        self,
        *,
        database: MarketUniverseDatabase | None = None,
        history_loader: HistoryLoader = yfinance_daily_history_loader,
        config: ReplayUniverseSelectionConfig | None = None,
    ) -> None:
        self.database = database or MarketUniverseDatabase()
        self.history_loader = history_loader
        self.config = config or ReplayUniverseSelectionConfig()

    def _catalogue_candidates(self) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            rows = db.execute(
                """
                SELECT ticker, company_name, exchange, asset_class
                FROM symbols
                WHERE tradable = 1
                  AND active = 1
                  AND (asset_class IS NULL OR asset_class = '' OR LOWER(asset_class) = 'us_equity')
                ORDER BY ticker
                LIMIT ?
                """,
                (int(self.config.candidate_limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def select(self) -> dict[str, Any]:
        candidates = self._catalogue_candidates()
        ranked: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []

        for asset in candidates:
            symbol = str(asset.get("ticker") or "").strip().upper()
            if not symbol:
                continue
            try:
                history = self.history_loader(symbol, period=self.config.history_period)
                metrics = historical_liquidity_metrics(history)
                sessions = int(metrics.get("history_sessions") or 0)
                adv = metrics.get("average_dollar_volume_20d")
                if adv is None or sessions < self.config.minimum_history_sessions:
                    continue
                adv = float(adv)
                if adv < self.config.minimum_average_dollar_volume:
                    continue
                ranked.append(
                    {
                        "symbol": symbol,
                        "company_name": asset.get("company_name"),
                        "exchange": asset.get("exchange"),
                        "asset_class": asset.get("asset_class"),
                        "average_dollar_volume_20d": adv,
                        "history_sessions": sessions,
                    }
                )
            except Exception as exc:
                failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

        ranked.sort(key=lambda row: (-float(row["average_dollar_volume_20d"]), row["symbol"]))
        selected = ranked[: int(self.config.top_n)]
        return {
            "selector_id": "replay-liquidity-universe-v1",
            "selection_metric": "average_dollar_volume_20d",
            "candidate_count": len(candidates),
            "eligible_count": len(ranked),
            "selected_count": len(selected),
            "top_n": int(self.config.top_n),
            "minimum_average_dollar_volume": float(self.config.minimum_average_dollar_volume),
            "symbols": [row["symbol"] for row in selected],
            "rankings": selected,
            "failures": failures,
        }
