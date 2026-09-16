from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sort_long_horizon_v5_recovery_artifacts.py"
SPEC = importlib.util.spec_from_file_location("sort_long_horizon_v5_recovery_artifacts", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SHA = "a" * 40


def _row(*, artifact_id: int = 1, run_id: int = 101, retention: timedelta) -> str:
    created = datetime(2026, 9, 16, 22, 0, tzinfo=timezone.utc)
    expires = created + retention
    return "\t".join(
        [
            str(artifact_id),
            f"long-horizon-v5-paired-shadow-{run_id}",
            created.isoformat().replace("+00:00", "Z"),
            expires.isoformat().replace("+00:00", "Z"),
            str(run_id),
            SHA,
        ]
    )


def test_accepts_exact_configured_retention() -> None:
    row = _row(retention=timedelta(days=45))
    assert MODULE.sort_artifact_rows([row]) == [row]


def test_accepts_small_github_timestamp_boundary_skew() -> None:
    row = _row(retention=timedelta(days=45) - timedelta(seconds=30))
    assert MODULE.sort_artifact_rows([row]) == [row]


def test_rejects_materially_short_retention() -> None:
    row = _row(retention=timedelta(days=45) - timedelta(minutes=6))
    with pytest.raises(ValueError, match="Artifact retention shorter than required"):
        MODULE.sort_artifact_rows([row])
