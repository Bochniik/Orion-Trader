from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Type


def _required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"missing_required_environment:{name}")
    return value


def _runtime_classes():
    """Import full backend runtime only when a real cloud cycle is executed.

    Focused orchestration tests intentionally avoid importing the complete market
    stack (and optional providers such as yfinance). The production workflow
    installs backend/requirements.txt before calling this script, so the real
    cloud path still uses the exact application implementations.
    """
    from app.services.alpaca_broker import AlpacaPaperBroker
    from app.services.market_data import MarketDataService
    from app.services.premarket_continuous_scheduler import PremarketContinuousScheduler

    return AlpacaPaperBroker, MarketDataService, PremarketContinuousScheduler


def run_cloud_cycle(
    *,
    output: Path,
    now: datetime | None = None,
    broker_factory: Callable[[], object] | None = None,
    market_factory: Callable[[], object] | None = None,
    scheduler_type: Type | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    # Fail closed on missing cloud credentials before importing the heavier
    # market-data stack. This keeps credential failure deterministic and makes
    # the cloud orchestration independently testable.
    key_id = _required_env("ALPACA_API_KEY_ID")
    secret_key = _required_env("ALPACA_API_SECRET_KEY")

    if broker_factory is None or market_factory is None or scheduler_type is None:
        AlpacaPaperBroker, MarketDataService, PremarketContinuousScheduler = _runtime_classes()
        broker_factory = broker_factory or AlpacaPaperBroker
        market_factory = market_factory or MarketDataService
        scheduler_type = scheduler_type or PremarketContinuousScheduler

    broker = broker_factory()
    user_id = "orion-cloud-premarket"
    broker.connect(user_id, key_id, secret_key)

    scheduler = scheduler_type(
        broker,
        market_factory(),
        interval_seconds=300,
        clock=lambda: now,
    )
    scheduler.activate_user(user_id)
    cycle = scheduler.run_cycle(user_id, now=now)
    state = scheduler.current_state(user_id)

    payload = {
        "contract": "orion-premarket-continuous-cloud-v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "cloud_independent_of_local_backend": True,
        "cycle": cycle,
        "state": state,
        "research_only": True,
        "order_submission_enabled": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="backend/data/cloud_shadow/premarket_continuous/latest.json",
    )
    args = parser.parse_args()
    payload = run_cloud_cycle(output=Path(args.output))
    print(json.dumps({
        "status": payload["state"].get("status"),
        "candidate_count": len(payload["state"].get("candidates") or []),
        "generated_at": payload["generated_at"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
