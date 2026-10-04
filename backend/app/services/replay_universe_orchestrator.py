"""Orchestrate liquidity selection into HistoricalUniverseRunner."""
from __future__ import annotations

from typing import Any, Mapping, Iterable

from app.services.historical_universe_runner import HistoricalUniverseRunner
from app.services.market_replay_engine import SIMULATED_FORWARD
from app.services.replay_universe_selector import ReplayLiquidityUniverseSelector


class ReplayUniverseOrchestrator:
    def __init__(
        self,
        *,
        selector: ReplayLiquidityUniverseSelector,
        runner: HistoricalUniverseRunner,
    ) -> None:
        self.selector = selector
        self.runner = runner

    def run(
        self,
        *,
        run_id: str | None = None,
        decision_times_by_symbol: Mapping[str, Iterable[Any]] | None = None,
    ) -> dict[str, Any]:
        selection = self.selector.select()
        symbols = list(selection.get("symbols") or [])
        if not symbols:
            raise RuntimeError("Liquidity selector returned no eligible replay symbols")

        result = self.runner.run(
            symbols,
            run_id=run_id,
            decision_times_by_symbol=decision_times_by_symbol,
        )
        if result.get("scope") != SIMULATED_FORWARD:
            raise RuntimeError("Historical runner returned non-simulated evidence")

        return {
            **result,
            "universe_selection": selection,
            "selection_metric": selection.get("selection_metric"),
            "selected_symbol_count": len(symbols),
            "selected_symbols": symbols,
        }
