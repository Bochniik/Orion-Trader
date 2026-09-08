
from __future__ import annotations

from typing import Any, Dict, Iterable

from app.services.market_universe_sync import (
    sync_assets_from_provider,
)
from app.services.market_universe_db import (
    MarketUniverseDatabase,
)


def sync_market_catalogue_from_assets(
    assets: Iterable[Dict[str, Any]],
    *,
    source: str = "alpaca_assets",
) -> Dict[str, Any]:
    """
    Stable adapter for importing the full provider tradable-universe response.

    Pass the same asset objects already returned by AlpacaPaperBroker.assets().
    No market ranking, Orion Score or recommendation logic is involved.
    """
    db = MarketUniverseDatabase()

    filtered = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and asset.get("tradable")
        and str(
            asset.get("status")
            or "active"
        ).lower() == "active"
    ]

    return sync_assets_from_provider(
        db,
        assets=filtered,
        source=source,
    )
