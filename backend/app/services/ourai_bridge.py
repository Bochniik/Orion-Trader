"""Explicit opt-in read-only OurAI V3 forward evidence bridge for local Orion.

Never calls trading/order APIs or imports the OurAI model. The ONLY permitted
upstream is fixed 127.0.0.1 with an operator-selected TCP port. Sanitizes the
external JSON response and fails closed on broken data or absent service.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
import json
import os

import httpx


FROZEN_SYMBOLS = ("NVDA", "AAPL", "TSLA", "JPM", "AMD", "META", "MSFT")
ROUTE = "/v1/forward-evidence"
MAX_EVIDENCE_BYTES = 262_144  # Bounded trusted-loopback JSON; never accept unbounded data.


def _inactive(state: str, reason: str | None = None) -> dict:
    result = {
        "status": state,
        "source": "ourai_local_forward_bridge",
        "experiment": "frozen_v3_magnitude_15m",
        "mode": "RESEARCH_SHADOW_ONLY",
        "direction_available": False,
        "trading_enabled": False,
        "message": (
            "Read-only integration not enabled."
            if state == "disabled" else
            "Verified local forward evidence unavailable; no results inferred."
        ),
    }
    if reason is not None:
        result["unavailable_reason"] = reason
    return result


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid forward evidence count")
    return value


def _metric(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid forward metric")
    out = float(value)
    if not isfinite(out) or out < 0:
        raise ValueError("invalid forward metric")
    return out


def _stamp(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid forward timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive forward timestamp")
    return value


def _validate_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("invalid forward evidence response")
    if (
        type(payload.get("schema_version")) is not int
        or payload["schema_version"] != 1
        or payload.get("source") != "ourai_verified_forward_journal"
        or payload.get("experiment") != "frozen_v3_magnitude_15m"
        or payload.get("mode") != "RESEARCH_SHADOW_ONLY"
        or payload.get("journal_valid") is not True
        or payload.get("horizon_minutes") != 15
        or payload.get("direction_available") is not False
        or payload.get("trading_enabled") is not False
    ):
        raise ValueError("OurAI forward evidence schema/semantics mismatch")
    predictions = _count(payload.get("prediction_count"))
    resolved = _count(payload.get("resolution_count"))
    pending = _count(payload.get("pending_count"))
    overdue = _count(payload.get("overdue_pending_count"))
    if resolved > predictions or predictions - resolved != pending or overdue > pending:
        raise ValueError("inconsistent forward evidence counts")

    metrics = {
        key: _metric(payload.get(key))
        for key in ("champion_mae_bps", "linear_mae_bps", "null_mae_bps")
    }
    if resolved == 0 and any(v is not None for v in metrics.values()):
        raise ValueError("unresolved forward evidence cannot have MAE")
    if resolved > 0 and any(v is None for v in metrics.values()):
        raise ValueError("resolved forward evidence requires all MAE baselines")

    raw_symbols = payload.get("symbols")
    raw_latest = payload.get("latest_by_symbol")
    if not isinstance(raw_symbols, dict) or not isinstance(raw_latest, dict):
        raise ValueError("invalid forward symbol mapping")
    if not set(raw_symbols) <= set(FROZEN_SYMBOLS) or not set(raw_latest) <= set(FROZEN_SYMBOLS):
        raise ValueError("unknown forward evidence symbol")
    symbols = {}
    for symbol, data in raw_symbols.items():
        if not isinstance(data, dict):
            raise ValueError("invalid forward symbol row")
        n = _count(data.get("predictions"))
        m = _count(data.get("resolved"))
        q = _count(data.get("pending"))
        overdue_symbol = _count(data.get("overdue_pending"))
        if n - m != q or overdue_symbol > q:
            raise ValueError("inconsistent per-symbol evidence counts")
        maae = tuple(_metric(data.get(key)) for key in ("champion_mae_bps", "linear_mae_bps", "null_mae_bps"))
        if (m == 0 and any(value is not None for value in maae)) or (m > 0 and any(value is None for value in maae)):
            raise ValueError("inconsistent per-symbol MAE availability")
        symbols[symbol] = {
            "predictions": n,
            "resolved": m,
            "pending": q,
            "overdue_pending": overdue_symbol,
            "champion_mae_bps": _metric(data.get("champion_mae_bps")),
            "linear_mae_bps": _metric(data.get("linear_mae_bps")),
            "null_mae_bps": _metric(data.get("null_mae_bps")),
        }
    if sum(x["predictions"] for x in symbols.values()) != predictions:
        raise ValueError("per-symbol prediction counts differ from total")
    if sum(x["resolved"] for x in symbols.values()) != resolved:
        raise ValueError("per-symbol resolution counts differ from total")
    if sum(x["pending"] for x in symbols.values()) != pending:
        raise ValueError("per-symbol pending counts differ from total")
    if sum(x["overdue_pending"] for x in symbols.values()) != overdue:
        raise ValueError("per-symbol overdue counts differ from total")

    # A latest row must exist for each symbol with a real journal prediction,
    # and no latest row may be invented for an empty symbol.
    if set(raw_latest) != {symbol for symbol, row in symbols.items() if row["predictions"] > 0}:
        raise ValueError("latest forecasts do not match symbol prediction counts")
    latest = {}
    for symbol, data in raw_latest.items():
        if not isinstance(data, dict) or data.get("symbol") != symbol:
            raise ValueError("invalid latest forecast identity")
        if type(data.get("resolved")) is not bool:
            raise ValueError("invalid latest forecast state")
        latest[symbol] = {
            "symbol": symbol,
            "predicted_at": _stamp(data.get("predicted_at")),
            "sample_timestamp": _stamp(data.get("sample_timestamp")),
            "target_due_at": _stamp(data.get("target_due_at")),
            "expected_magnitude_bps": _metric(data.get("expected_magnitude_bps")),
            "resolved": data["resolved"],
        }
        if latest[symbol]["expected_magnitude_bps"] is None:
            raise ValueError("missing latest magnitude")
        if data["resolved"] and symbols[symbol]["resolved"] == 0:
            raise ValueError("latest forecast resolved without symbol resolutions")
        if not data["resolved"] and symbols[symbol]["pending"] == 0:
            raise ValueError("latest forecast pending without symbol pending count")
        sample_at = datetime.fromisoformat(latest[symbol]["sample_timestamp"].replace("Z", "+00:00"))
        predicted_at = datetime.fromisoformat(latest[symbol]["predicted_at"].replace("Z", "+00:00"))
        due_at = datetime.fromisoformat(latest[symbol]["target_due_at"].replace("Z", "+00:00"))
        if not sample_at <= predicted_at < due_at:
            raise ValueError("inconsistent latest forecast chronology")
    if not set(latest) <= set(symbols):
        raise ValueError("latest forecasts absent from symbol counts")
    return {
        "status": "available",
        "source": "ourai_verified_forward_journal",
        "experiment": "frozen_v3_magnitude_15m",
        "mode": "RESEARCH_SHADOW_ONLY",
        "horizon_minutes": 15,
        "direction_available": False,
        "trading_enabled": False,
        "as_of": _stamp(payload.get("evaluated_at_utc")),
        "prediction_count": predictions,
        "resolution_count": resolved,
        "pending_count": pending,
        "overdue_pending_count": overdue,
        **metrics,
        "symbols": symbols,
        "latest_by_symbol": latest,
        "disclaimer": (
            "Verified 15m absolute magnitude only; no UP/DOWN forecast, "
            "trading signal or independent proof of profitability."
        ),
    }


def fetch_ourai_forward_evidence(
    *,
    enabled: bool | None = None,
    port: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Fetch sanitized evidence; no outbound hosts, credentials, writes or orders."""
    if enabled is None:
        enabled = os.getenv("OURAI_BRIDGE_ENABLED", "false").lower() == "true"
    if not enabled:
        return _inactive("disabled")
    try:
        if port is None:
            port = int(os.getenv("OURAI_BRIDGE_PORT", "8765"))
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid loopback port")
        with httpx.Client(timeout=2.0, trust_env=False, transport=transport) as client:
            with client.stream("GET", f"http://127.0.0.1:{port}{ROUTE}") as response:
                response.raise_for_status()
                # Cap decoded bytes, not just Content-Length, before parsing:
                # a local listener can be replaced or return compressed data.
                chunks = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_EVIDENCE_BYTES:
                        raise ValueError("oversized forward evidence response")
                    chunks.append(chunk)
            return _validate_payload(json.loads(b"".join(chunks)))
    except httpx.TransportError:
        # All loopback transport failures (DNS/connect/read/write/pool/protocol)
        # are data-availability failures, not evidence of model inaccuracy.
        return _inactive("unavailable", "upstream_connection_failure")
    except httpx.HTTPStatusError:
        return _inactive("unavailable", "upstream_http_failure")
    except (ValueError, TypeError, KeyError, httpx.HTTPError):
        return _inactive("unavailable", "invalid_upstream_evidence")
