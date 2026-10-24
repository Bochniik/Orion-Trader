"""Leakage-safe frozen symbol specialist engine for Orion research.

The engine learns only additive logistic calibration offsets from a frozen
development cohort and can then be evaluated on an untouched lockbox without
updating its parameters. It is research-only and cannot route LIVE_FORWARD
predictions or auto-promote itself.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping, Sequence

ENGINE_FAMILY = "orion-frozen-symbol-specialist-v1"


def _session(timestamp: str) -> str:
    return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).date().isoformat()


def _probability(value: Any) -> float:
    p = float(value)
    if p > 1.0:
        p /= 100.0
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise ValueError("probability must be finite and strictly between 0 and 1")
    return min(max(p, 1e-6), 1.0 - 1e-6)


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _fit_offset(rows: Sequence[Mapping[str, Any]], parent_offsets: Sequence[float], ridge: float) -> float:
    if len(rows) != len(parent_offsets):
        raise ValueError("rows/parent_offsets length mismatch")
    offset = 0.0
    for _ in range(40):
        gradient = ridge * offset
        hessian = ridge
        for row, parent_offset in zip(rows, parent_offsets):
            p = _sigmoid(_logit(_probability(row["p_up"])) + parent_offset + offset)
            y = int(row["actual_up"])
            if y not in (0, 1):
                raise ValueError("actual_up must be 0/1")
            gradient += p - y
            hessian += p * (1.0 - p)
        if hessian <= 0:
            break
        step = gradient / hessian
        offset -= step
        if abs(step) < 1e-10:
            break
    return float(min(max(offset, -3.0), 3.0))


def _enough(rows: Sequence[Mapping[str, Any]], min_obs: int, min_sessions: int) -> bool:
    return len(rows) >= min_obs and len({_session(str(row["timestamp"])) for row in rows}) >= min_sessions


@dataclass(frozen=True)
class FrozenSymbolSpecialistModel:
    symbol: str
    sector: str
    horizon: str
    global_offset: float
    sector_offset: float
    symbol_offset: float
    development_observations: int
    development_sessions: int
    symbol_observations: int
    symbol_sessions: int
    development_last_session: str
    ridge: float
    engine_family: str = ENGINE_FAMILY
    research_only: bool = True
    automatic_live_promotion: bool = False
    runtime_influence_allowed: bool = False

    @property
    def model_id(self) -> str:
        payload = asdict(self)
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
        return f"{self.engine_family}:{self.symbol}:{self.horizon}:{digest}"

    def predict(self, base_probability_up: float) -> dict[str, float]:
        base = _probability(base_probability_up)
        parent = _sigmoid(_logit(base) + self.global_offset + self.sector_offset)
        specialist = _sigmoid(_logit(base) + self.global_offset + self.sector_offset + self.symbol_offset)
        return {
            "base_probability_up": base,
            "incumbent_probability_up": parent,
            "specialist_probability_up": specialist,
        }

    def registration(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "model_id": self.model_id,
            "same_evidence_approval_forbidden": True,
            "requires_untouched_lockbox": True,
        }


class FrozenSymbolSpecialistEngine:
    """Fit one frozen global->sector->symbol calibration hierarchy on development data."""

    @staticmethod
    def fit(
        records: Iterable[Mapping[str, Any]],
        *,
        symbol: str,
        sector: str,
        horizon: str,
        min_global_obs: int = 200,
        min_global_sessions: int = 10,
        min_sector_obs: int = 100,
        min_sector_sessions: int = 8,
        min_symbol_obs: int = 60,
        min_symbol_sessions: int = 8,
        ridge: float = 8.0,
    ) -> FrozenSymbolSpecialistModel:
        rows = sorted((dict(row) for row in records), key=lambda row: (str(row["timestamp"]), str(row["symbol"])))
        ticker = str(symbol).strip().upper()
        target_sector = str(sector).strip()
        if not rows or not ticker or not target_sector or not str(horizon).strip():
            raise ValueError("development records, symbol, sector and horizon are required")
        sector_rows = [row for row in rows if str(row.get("sector")) == target_sector]
        symbol_rows = [row for row in rows if str(row.get("symbol", "")).upper() == ticker]
        if not _enough(rows, min_global_obs, min_global_sessions):
            raise RuntimeError("insufficient global development evidence")
        if not _enough(sector_rows, min_sector_obs, min_sector_sessions):
            raise RuntimeError("insufficient sector development evidence")
        if not _enough(symbol_rows, min_symbol_obs, min_symbol_sessions):
            raise RuntimeError("insufficient symbol development evidence")

        global_offset = _fit_offset(rows, [0.0] * len(rows), ridge)
        sector_offset = _fit_offset(sector_rows, [global_offset] * len(sector_rows), ridge)
        symbol_offset = _fit_offset(
            symbol_rows,
            [global_offset + sector_offset] * len(symbol_rows),
            ridge,
        )
        sessions = sorted({_session(str(row["timestamp"])) for row in rows})
        symbol_sessions = sorted({_session(str(row["timestamp"])) for row in symbol_rows})
        return FrozenSymbolSpecialistModel(
            symbol=ticker,
            sector=target_sector,
            horizon=str(horizon),
            global_offset=global_offset,
            sector_offset=sector_offset,
            symbol_offset=symbol_offset,
            development_observations=len(rows),
            development_sessions=len(sessions),
            symbol_observations=len(symbol_rows),
            symbol_sessions=len(symbol_sessions),
            development_last_session=sessions[-1],
            ridge=float(ridge),
        )
