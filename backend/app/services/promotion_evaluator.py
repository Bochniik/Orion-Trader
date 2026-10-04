from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


def benjamini_hochberg(rows: Iterable[Mapping[str, Any]], alpha: float = 0.05) -> dict[str, bool]:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    values = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "").strip()
        p_value = row.get("p_value")
        if not candidate_id or not isinstance(p_value, (int, float)):
            raise ValueError("complete candidate_id and p_value evidence required")
        p_value = float(p_value)
        if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
            raise ValueError("p_value must be finite and in [0,1]")
        values.append((candidate_id, p_value))
    if len({key for key, _ in values}) != len(values):
        raise ValueError("candidate_id must be unique")
    ranked = sorted(values, key=lambda item: (item[1], item[0]))
    cutoff = 0
    for rank, (_, p_value) in enumerate(ranked, 1):
        if p_value <= alpha * rank / len(ranked):
            cutoff = rank
    accepted = {key: False for key, _ in values}
    for key, _ in ranked[:cutoff]:
        accepted[key] = True
    return accepted
