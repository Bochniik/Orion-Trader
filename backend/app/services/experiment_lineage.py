"""Deterministic experiment lineage for causal Orion research.

Hashes are evidence identifiers, not performance metrics.  Invalid or incomplete
material fails closed instead of silently producing a misleading fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


LINEAGE_CONTRACT = "orion-experiment-lineage-v1"
_REQUIRED_SAMPLE_FIELDS = ("symbol", "timestamp", "outcome_timestamp", "horizon", "actual_direction")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("lineage material must be canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def feature_set_sha256(feature_names: Sequence[str]) -> str:
    if isinstance(feature_names, (str, bytes)):
        raise ValueError("feature_names must be a sequence")
    normalized = [str(name).strip() for name in feature_names]
    if not normalized or any(not name for name in normalized):
        raise ValueError("feature_names must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("feature_names must be unique")
    return _sha256(sorted(normalized))


def dataset_sha256(samples: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> str:
    features = sorted(str(name).strip() for name in feature_names)
    feature_set_sha256(features)
    if not samples:
        raise ValueError("dataset must contain at least one sample")

    material = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise ValueError("every dataset sample must be an object")
        missing = [field for field in _REQUIRED_SAMPLE_FIELDS if sample.get(field) in (None, "")]
        if missing:
            raise ValueError("dataset sample missing required fields: " + ", ".join(missing))
        values = sample.get("features")
        if not isinstance(values, Mapping):
            raise ValueError("dataset sample features must be an object")
        missing_features = [name for name in features if name not in values]
        if missing_features:
            raise ValueError("dataset sample missing features: " + ", ".join(missing_features))
        selected = {}
        for name in features:
            value = values[name]
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("dataset features must be finite or null")
            selected[name] = value
        material.append({
            "symbol": str(sample["symbol"]),
            "timestamp": str(sample["timestamp"]),
            "outcome_timestamp": str(sample["outcome_timestamp"]),
            "horizon": str(sample["horizon"]),
            "actual_direction": str(sample["actual_direction"]),
            "actual_return": sample.get("actual_return"),
            "features": selected,
        })

    material.sort(key=lambda row: (
        row["timestamp"], row["symbol"], row["horizon"], row["outcome_timestamp"]
    ))
    return _sha256(material)


def build_experiment_lineage(
    *,
    samples: Sequence[Mapping[str, Any]],
    feature_names: Sequence[str],
    code_sha: str,
    horizon: str,
    split_config: Mapping[str, Any],
    parent_experiment_sha256: str | None = None,
) -> dict[str, Any]:
    code = str(code_sha).strip()
    selected_horizon = str(horizon).strip()
    if not code or not selected_horizon:
        raise ValueError("code_sha and horizon are required")
    if not isinstance(split_config, Mapping) or not split_config:
        raise ValueError("split_config is required")

    feature_hash = feature_set_sha256(feature_names)
    data_hash = dataset_sha256(samples, feature_names)
    core = {
        "contract": LINEAGE_CONTRACT,
        "code_sha": code,
        "horizon": selected_horizon,
        "dataset_sha256": data_hash,
        "feature_set_sha256": feature_hash,
        "split_config": dict(split_config),
        "parent_experiment_sha256": str(parent_experiment_sha256).strip() or None
        if parent_experiment_sha256 is not None else None,
    }
    return {**core, "experiment_sha256": _sha256(core)}
