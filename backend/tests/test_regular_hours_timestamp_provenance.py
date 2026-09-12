from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
for path in (str(BACKEND), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module("regular_hours_shadow_provenance", SCRIPTS / "run_regular_hours_v3_1_cloud_shadow.py")
evaluator = load_module("cloud_shadow_evaluator_provenance", SCRIPTS / "evaluate_cloud_shadow_predictions.py")


def regular_payload(*, as_of="2026-09-11T14:05:00+00:00", aligned=True):
    return {
        "created_at_utc": "2026-09-11T14:07:00+00:00",
        "lineage": {"git_commit": "abc"},
        "results": {
            "symbols": {
                "AAPL": {
                    "available": True,
                    "as_of": as_of,
                    "source_timestamp_aligned": aligned,
                    "source_as_of": {
                        "v1": "2026-09-11T14:05:00+00:00",
                        "v2": "2026-09-11T14:05:00+00:00" if aligned else "2026-09-11T14:10:00+00:00",
                    },
                    "reliability_profile_source": "ticker_specific_walk_forward_60d_5m",
                    "profile_validated_for_symbol": True,
                    "horizons": {
                        "30m": {
                            "available": True,
                            "probability_up": 61.0,
                            "direction": "bullish",
                            "suppressed": False,
                        }
                    },
                }
            }
        },
    }


def test_runner_preserves_source_timestamp_provenance():
    raw = {
        "available": True,
        "as_of": "2026-09-11T14:05:00+00:00",
        "source_timestamp_aligned": True,
        "source_as_of": {
            "v1": "2026-09-11T14:05:00+00:00",
            "v2": "2026-09-11T14:05:00+00:00",
        },
        "engine_version": "V3.1",
        "horizons": {},
        "warnings": [],
    }
    summary = runner.summarize_symbol("AAPL", raw)
    assert summary["as_of"] == raw["as_of"]
    assert summary["source_timestamp_aligned"] is True
    assert summary["source_as_of"] == raw["source_as_of"]


def test_regular_hours_aligned_source_timestamp_is_evaluable():
    rows = list(evaluator.iter_forecasts(regular_payload(), "prediction.json"))
    assert len(rows) == 1
    assert rows[0]["prediction_time"] == "2026-09-11T14:05:00+00:00"
    assert rows[0]["engine"] == "regular_hours_v3_1"


def test_regular_hours_missing_source_timestamp_does_not_fallback_to_artifact_creation_time():
    payload = regular_payload(as_of=None, aligned=False)
    rows = list(evaluator.iter_forecasts(payload, "prediction.json"))
    assert rows == []


def test_regular_hours_unaligned_source_timestamps_are_not_evaluable_even_with_as_of_present():
    payload = regular_payload(as_of="2026-09-11T14:05:00+00:00", aligned=False)
    rows = list(evaluator.iter_forecasts(payload, "prediction.json"))
    assert rows == []


def test_regular_hours_missing_alignment_proof_fails_closed():
    payload = regular_payload()
    del payload["results"]["symbols"]["AAPL"]["source_timestamp_aligned"]
    rows = list(evaluator.iter_forecasts(payload, "prediction.json"))
    assert rows == []
