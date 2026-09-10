from __future__ import annotations

import csv
import importlib.util
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "collect_cloud_shadow_outcome_bars.py"
spec = importlib.util.spec_from_file_location("collect_cloud_shadow_outcome_bars", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def forecast(*, horizon: str, prediction_time: str = "2026-09-10T14:00:00+00:00"):
    return {
        "engine": "regular_hours_v3_1",
        "symbol": "AAPL",
        "horizon": horizon,
        "prediction_time": prediction_time,
        "probability_up": 0.61,
        "direction": "UP",
    }


def test_request_windows_include_only_mature_horizons_and_are_tightly_bounded():
    cutoff = datetime(2026, 9, 10, 14, 31, tzinfo=timezone.utc)
    windows, stats = module.build_request_windows(
        [forecast(horizon="5m"), forecast(horizon="15m"), forecast(horizon="1h")],
        cutoff=cutoff,
        max_age_days=35,
    )

    assert stats == {"forecasts_seen": 3, "future_horizon": 1, "too_old": 0, "mature": 2}
    assert len(windows) == 1
    window = windows[0]
    assert window.mature_horizons == ("5m", "15m")
    assert window.start_utc == "2026-09-10T13:55:00+00:00"
    assert window.end_utc == "2026-09-10T14:21:00+00:00"


def test_old_predictions_are_skipped_before_any_market_data_request_is_planned():
    cutoff = datetime(2026, 9, 10, 14, 31, tzinfo=timezone.utc)
    windows, stats = module.build_request_windows(
        [forecast(horizon="5m", prediction_time="2026-07-01T14:00:00+00:00")],
        cutoff=cutoff,
        max_age_days=35,
    )

    assert windows == []
    assert stats["too_old"] == 1
    assert stats["mature"] == 0


def test_prediction_times_are_not_merged_into_one_large_unbounded_window():
    cutoff = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    windows, _ = module.build_request_windows(
        [
            forecast(horizon="15m", prediction_time="2026-09-10T14:00:00+00:00"),
            forecast(horizon="15m", prediction_time="2026-09-10T15:00:00+00:00"),
        ],
        cutoff=cutoff,
    )

    assert len(windows) == 2
    assert windows[0].start_utc == "2026-09-10T13:55:00+00:00"
    assert windows[0].end_utc == "2026-09-10T14:21:00+00:00"
    assert windows[1].start_utc == "2026-09-10T14:55:00+00:00"
    assert windows[1].end_utc == "2026-09-10T15:21:00+00:00"


def test_write_bars_deduplicates_and_rejects_rows_outside_planned_window(tmp_path):
    window = module.OutcomeWindow(
        engine="premarket_v5",
        symbol="NVDA",
        prediction_time_utc="2026-09-10T13:15:00+00:00",
        start_utc="2026-09-10T13:10:00+00:00",
        end_utc="2026-09-10T13:26:00+00:00",
        mature_horizons=("5m",),
    )
    rows = [
        {"t": "2026-09-10T13:09:00Z", "c": 99.0},
        {"t": "2026-09-10T13:10:00Z", "c": 100.0},
        {"t": "2026-09-10T13:10:00Z", "c": 100.0},
        {"t": "2026-09-10T13:25:00Z", "c": 101.0},
        {"t": "2026-09-10T13:26:00Z", "c": 102.0},
    ]
    output = tmp_path / "bars.csv"

    written = module.write_bars(output, [(window, rows)])

    assert written == 2
    with output.open("r", encoding="utf-8", newline="") as handle:
        saved = list(csv.DictReader(handle))
    assert [row["timestamp"] for row in saved] == [
        "2026-09-10T13:10:00+00:00",
        "2026-09-10T13:25:00+00:00",
    ]
