"""Read-only JPM provider/universe probe; never validates settled OOS evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from app.services.cloud_learning_shards import CLOUD_REPLAY_SYMBOLS
from app.services.symbol_specialist_engines import TARGET_SYMBOLS


def inspect_provider(*, fetch: Callable | None = None, now: datetime | None = None) -> dict:
    """Probe actual yfinance bars only when fetch is omitted.

    Injected fetchers are for synthetic tests; their results can never be
    described as a verified real provider response.
    """
    live = fetch is None
    result = {
        "contract": "orion-jpm-provider-universe-preflight-v1",
        "symbol": "JPM", "scope": "SIMULATED_FORWARD", "research_only": True,
        "registered_specialist": "JPM" in TARGET_SYMBOLS,
        "registered_replay_universe": "JPM" in CLOUD_REPLAY_SYMBOLS,
        "provider": "yfinance", "live_provider_checked": live,
        "provider_validated": False, "bars_observed": None,
        "first_bar_utc": None, "last_bar_utc": None,
        "settled_samples_verified": False, "lockbox_certified_untouched": False,
        "live_forward_mutated": False, "production_activated": False,
        "verdict": "AWAITING_MORE_EVIDENCE", "reason": "provider_not_checked",
    }
    if not result["registered_specialist"] or not result["registered_replay_universe"]:
        result["reason"] = "symbol_not_registered"
        return result
    try:
        if fetch is None:
            import yfinance as yf
            fetch = lambda: yf.Ticker("JPM").history(
                period="5d", interval="5m", prepost=False, auto_adjust=False
            )
        frame = fetch()
        if frame is None or frame.empty or "Close" not in frame.columns:
            result["reason"] = "empty_or_invalid_provider_frame"
            return result
        times = frame.index
        if getattr(times, "tz", None) is None or not times.is_monotonic_increasing or times.has_duplicates:
            result["reason"] = "invalid_or_unzoned_timestamps"
            return result
        closes = frame["Close"].astype(float)
        import numpy as np
        if not bool(np.isfinite(closes.to_numpy()).all()) or not bool((closes > 0).all()):
            result["reason"] = "invalid_close_prices"
            return result
        first = times[0].to_pydatetime().astimezone(timezone.utc)
        last = times[-1].to_pydatetime().astimezone(timezone.utc)
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        age_seconds = (clock.astimezone(timezone.utc) - last).total_seconds()
        result.update(bars_observed=len(frame), first_bar_utc=first.isoformat(),
                      last_bar_utc=last.isoformat())
        if len(frame) < 10 or not (0 <= age_seconds <= 7 * 86400):
            result["reason"] = "insufficient_or_stale_bars"
            return result
        if not live:
            result["reason"] = "synthetic_fetcher_not_provenance"
            return result
        result["provider_validated"] = True
        result["reason"] = "provider_connectivity_only_no_settled_evidence"
    except Exception as exc:
        result["reason"] = "provider_probe_error:" + type(exc).__name__
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only JPM provider probe")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = inspect_provider()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
