from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.services.alpaca_broker import AlpacaPaperBroker
from app.services.market_data import MarketDataService
from app.services.premarket_continuous_scheduler import PremarketContinuousScheduler


def _required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"missing_required_environment:{name}")
    return value


def run_cloud_cycle(*, output: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    broker = AlpacaPaperBroker()
    user_id = "orion-cloud-premarket"
    broker.connect(
        user_id,
        _required_env("ALPACA_API_KEY_ID"),
        _required_env("ALPACA_API_SECRET_KEY"),
    )

    scheduler = PremarketContinuousScheduler(
        broker,
        MarketDataService(),
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
