from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable

import numpy as np
import pandas as pd

from app.services.premarket_live_engine import synthesize_live_premarket_candidate
from app.services.premarket_v5_runtime import predict_premarket_v5_outlook

HORIZONS = (5, 15, 30)


@dataclass(frozen=True)
class Scenario:
    name: str
    gap_pct: float
    drift_pct_per_minute: float
    noise_pct: float
    reversal_minute: int | None = None
    reversal_drift_pct_per_minute: float | None = None
    volume_scale: float = 1.0
    bar_probability: float = 1.0


SCENARIOS = (
    Scenario("trend_up", 3.0, 0.018, 0.055, volume_scale=1.30),
    Scenario("trend_down", -3.0, -0.018, 0.055, volume_scale=1.30),
    Scenario("gap_up_fade", 4.5, -0.022, 0.070, volume_scale=1.10),
    Scenario("gap_down_recovery", -4.5, 0.022, 0.070, volume_scale=1.10),
    Scenario("mid_session_reversal", 1.5, -0.014, 0.060, reversal_minute=165, reversal_drift_pct_per_minute=0.024, volume_scale=1.20),
    Scenario("chop", 0.2, 0.0, 0.110, volume_scale=0.85),
    Scenario("sparse_illiquid", 1.0, 0.006, 0.160, volume_scale=0.20, bar_probability=0.38),
)


def _session_index(session_date: str) -> pd.DatetimeIndex:
    start = pd.Timestamp(f"{session_date} 04:00", tz="America/New_York")
    return pd.date_range(start=start, periods=330, freq="min").tz_convert("UTC")


def generate_scenario(
    scenario: Scenario,
    *,
    session_date: str = "2026-10-08",
    previous_close: float = 100.0,
    seed: int = 7,
) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    index = _session_index(session_date)
    close = np.empty(len(index), dtype=float)
    price = previous_close * (1.0 + scenario.gap_pct / 100.0)

    for minute in range(len(index)):
        drift = scenario.drift_pct_per_minute
        if scenario.reversal_minute is not None and minute >= scenario.reversal_minute:
            drift = float(scenario.reversal_drift_pct_per_minute or 0.0)
        shock = rng.normal(0.0, scenario.noise_pct)
        price *= 1.0 + (drift + shock) / 100.0
        price = max(price, 1.0)
        close[minute] = price

    latent = pd.Series(close, index=index, name="Close")
    prior = np.concatenate(([previous_close * (1.0 + scenario.gap_pct / 100.0)], close[:-1]))
    open_ = prior
    wiggle = np.maximum(np.abs(rng.normal(0.035, 0.02, len(index))), 0.008) / 100.0
    high = np.maximum(open_, close) * (1.0 + wiggle)
    low = np.minimum(open_, close) * (1.0 - wiggle)
    base_volume = 45_000.0 * scenario.volume_scale
    shape = 0.65 + 1.6 * np.abs(np.linspace(-1.0, 1.0, len(index)))
    volume = np.maximum(100.0, base_volume * shape * rng.lognormal(mean=0.0, sigma=0.35, size=len(index)))

    frame = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )
    if scenario.bar_probability < 1.0:
        keep = rng.random(len(frame)) < scenario.bar_probability
        keep[0] = True
        keep[-1] = True
        frame = frame.loc[keep]
    return frame, latent


def _future_close(latent: pd.Series, as_of: pd.Timestamp, horizon: int) -> float | None:
    target = as_of + pd.Timedelta(minutes=horizon)
    if target not in latent.index:
        return None
    return float(latent.loc[target])


def _settle_signal(row: dict, latent: pd.Series, as_of: pd.Timestamp, horizon: int) -> dict | None:
    future = _future_close(latent, as_of, horizon)
    if future is None:
        return None
    now_price = float(latent.loc[as_of])
    actual_return = (future / now_price - 1.0) * 100.0
    actual_up = actual_return > 0.0
    probability_up = row.get("probability_up")
    predicted_direction = str(row.get("direction") or "NO_TRADE")
    raw_direction = str(row.get("raw_direction") or "")
    return {
        "horizon_minutes": horizon,
        "actual_return_pct": actual_return,
        "actual_up": actual_up,
        "probability_up": probability_up,
        "research_gate_passed": row.get("research_gate_passed") is True,
        "predicted_direction": predicted_direction,
        "raw_direction": raw_direction,
        "correct_when_traded": None if predicted_direction == "NO_TRADE" else ((predicted_direction == "UP") == actual_up),
        "raw_direction_correct": None if raw_direction not in {"UP", "DOWN"} else ((raw_direction == "UP") == actual_up),
        "brier": None if probability_up is None else (float(probability_up) - (1.0 if actual_up else 0.0)) ** 2,
    }


def run_scenario(
    scenario: Scenario,
    *,
    session_date: str = "2026-10-08",
    previous_close: float = 100.0,
    seed: int = 7,
    evaluation_step_minutes: int = 5,
) -> dict:
    frame, latent = generate_scenario(
        scenario,
        session_date=session_date,
        previous_close=previous_close,
        seed=seed,
    )
    evaluation_points = latent.index[60:-30:evaluation_step_minutes]
    snapshots = []
    settlements = []

    for as_of in evaluation_points:
        visible = frame.loc[frame.index <= as_of]
        if len(visible) < 3:
            continue
        v5 = predict_premarket_v5_outlook(
            visible,
            previous_close=previous_close,
            feed="sip",
            as_of=as_of,
        )
        live = synthesize_live_premarket_candidate(
            ticker=scenario.name.upper()[:15],
            setup={"score": 65.0, "data_quality_component": 90.0},
            rank={
                "premarket_rank_score": 70.0,
                "premarket_rank_components": {"data_quality_score": 90.0},
            },
            v5_outlook=v5,
            now=as_of.to_pydatetime(),
        )
        snapshots.append(
            {
                "as_of": as_of.isoformat(),
                "direction": live.get("direction"),
                "probability_up": live.get("probability_up"),
                "probability_down": live.get("probability_down"),
                "premarket_orion_score": live.get("premarket_orion_score"),
                "research_gate_pass_count": live.get("research_gate_pass_count", 0),
                "horizon_consistency": live.get("horizon_consistency"),
                "v5_available": v5.get("available") is True,
            }
        )
        for horizon in HORIZONS:
            signal = (v5.get("signals") or {}).get(f"premarket_{horizon}m")
            if not isinstance(signal, dict):
                continue
            settled = _settle_signal(signal, latent, as_of, horizon)
            if settled is not None:
                settlements.append(settled)

    gated = [row for row in settlements if row["predicted_direction"] != "NO_TRADE"]
    raw = [row for row in settlements if row["raw_direction_correct"] is not None]
    briers = [row["brier"] for row in settlements if row["brier"] is not None]
    scores = [float(row["premarket_orion_score"]) for row in snapshots if row.get("premarket_orion_score") is not None]
    by_horizon: Dict[str, dict] = {}
    for horizon in HORIZONS:
        rows = [row for row in settlements if row["horizon_minutes"] == horizon]
        traded = [row for row in rows if row["predicted_direction"] != "NO_TRADE"]
        horizon_briers = [float(row["brier"]) for row in rows if row["brier"] is not None]
        by_horizon[str(horizon)] = {
            "samples": len(rows),
            "trade_signals": len(traded),
            "signal_rate": 0.0 if not rows else len(traded) / len(rows),
            "directional_accuracy_when_traded": None if not traded else sum(bool(row["correct_when_traded"]) for row in traded) / len(traded),
            "brier": None if not horizon_briers else sum(horizon_briers) / len(horizon_briers),
        }

    return {
        "scenario": scenario.name,
        "bar_count": len(frame),
        "latent_minute_count": len(latent),
        "snapshot_count": len(snapshots),
        "settlement_count": len(settlements),
        "trade_signal_count": len(gated),
        "signal_rate": 0.0 if not settlements else len(gated) / len(settlements),
        "no_trade_rate": 1.0 if not settlements else 1.0 - (len(gated) / len(settlements)),
        "directional_accuracy_when_traded": None if not gated else sum(bool(row["correct_when_traded"]) for row in gated) / len(gated),
        "raw_direction_accuracy": None if not raw else sum(bool(row["raw_direction_correct"]) for row in raw) / len(raw),
        "brier": None if not briers else sum(briers) / len(briers),
        "average_orion_score": None if not scores else sum(scores) / len(scores),
        "max_orion_score": None if not scores else max(scores),
        "by_horizon": by_horizon,
        "snapshots": snapshots,
    }


def run_lab(
    *,
    session_date: str = "2026-10-08",
    seed: int = 7,
    scenarios: Iterable[Scenario] = SCENARIOS,
) -> dict:
    results = [
        run_scenario(scenario, session_date=session_date, seed=seed + index * 101)
        for index, scenario in enumerate(scenarios)
    ]
    live_direction_snapshots = sum(
        1
        for result in results
        for row in result.get("snapshots", [])
        if row.get("direction") in {"UP", "DOWN"}
    )
    return {
        "contract": "orion-premarket-synthetic-lab-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_date": session_date,
        "seed": seed,
        "scenario_count": len(results),
        "research_only": True,
        "order_submission_enabled": False,
        "purpose": "Synthetic stress/replay testing only; not evidence of live-market profitability.",
        "scenarios": results,
        "live_direction_snapshot_count": live_direction_snapshots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic synthetic Premarket V5 stress/replay lab")
    parser.add_argument("--session-date", default="2026-10-08")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default="backend/data/simulations/premarket_synthetic_lab.json")
    args = parser.parse_args()
    payload = run_lab(session_date=args.session_date, seed=args.seed)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "scenario_count": payload["scenario_count"],
        "live_direction_snapshot_count": payload["live_direction_snapshot_count"],
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
