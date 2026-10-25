"""Explicit opt-in read-only OurAI V3 forward evidence bridge for local Orion.

Never calls trading/order APIs or imports the OurAI model. The ONLY permitted
upstream is fixed 127.0.0.1 with an operator-selected TCP port. Sanitizes the
external JSON response and fails closed on broken data or absent service.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isclose, isfinite
from time import monotonic
import json
import os

import httpx


FROZEN_SYMBOLS = ("NVDA", "AAPL", "TSLA", "JPM", "AMD", "META", "MSFT")
ROUTE = "/v1/forward-evidence"
MAX_EVIDENCE_BYTES = 262_144  # Bounded trusted-loopback JSON; never accept unbounded data.
MAX_RESPONSE_SECONDS = 5.0  # A slow-trickling peer must not occupy a worker indefinitely.


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

    # OurAI reports rounded (3-decimal) MAE separately by symbol and globally.
    # The global value must agree with the resolved-count-weighted symbol mean.
    # Allow at most 0.0011 bps for the two independent rounding operations;
    # pending predictions never contribute to an MAE or its weight.
    if resolved:
        for key, global_mae in metrics.items():
            weighted_mae = sum(
                row[key] * row["resolved"]
                for row in symbols.values() if row["resolved"]
            ) / resolved
            if not isclose(weighted_mae, global_mae, rel_tol=1e-12, abs_tol=0.0011):
                raise ValueError("global forward MAE differs from resolved symbol evidence")

    # A latest row must exist for each symbol with a real journal prediction,
    # and no latest row may be invented for an empty symbol.
    if set(raw_latest) != {symbol for symbol, row in symbols.items() if row["predictions"] > 0}:
        raise ValueError("latest forecasts do not match symbol prediction counts")
    evaluated_at = _stamp(payload.get("evaluated_at_utc"))
    evaluated_dt = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
    # Reject a report claiming verification far in the future. A small skew
    # allowance tolerates imperfect desktop clocks without accepting forged
    # forward chronology as already observed evidence.
    if evaluated_dt > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("future forward evidence evaluation timestamp")
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
        if (due_at - sample_at != timedelta(minutes=15)
                or not sample_at <= predicted_at < due_at
                or predicted_at > evaluated_dt
                # A resolved forecast cannot have reached its 15m target
                # after the report was evaluated. Pending may be overdue.
                or (data["resolved"] and due_at > evaluated_dt)):
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
        "as_of": evaluated_at,
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



def _reject_json_constant(_value: str) -> None:
    """Python accepts NaN/Infinity by default, but these are not JSON numbers."""
    raise ValueError("nonstandard JSON numeric constant")


def _finite_json_float(value: str) -> float:
    """Reject numeric exponent overflow even in ignored upstream fields."""
    number = float(value)
    if not isfinite(number):
        raise ValueError("nonfinite JSON number")
    return number


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict:
    """Reject ambiguous evidence rather than letting JSON's last key win."""
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate forward evidence JSON key")
        obj[key] = value
    return obj


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
        # Per-operation timeouts alone permit an endless slow-trickle response.
        # Enforce a total deadline as well, without changing read-only semantics.
        started_at = monotonic()
        # Redirects must never send evidence requests outside trusted loopback.
        # Explicitly pin this instead of relying on httpx defaults.
        with httpx.Client(timeout=2.0, trust_env=False, follow_redirects=False, transport=transport) as client:
            with client.stream(
                "GET", f"http://127.0.0.1:{port}{ROUTE}",
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                # The fixed read-only producer returns exactly HTTP 200.
                # Other 2xx statuses (including 206 partial content) must not
                # be promoted into verified evidence even with valid JSON.
                if response.status_code != 200:
                    return _inactive("unavailable", "upstream_http_failure")
                # OurAI's producer sends plain JSON. Reject compression rather
                # than allocating an arbitrarily large decoded chunk before
                # the byte limit can be checked (decompression-bomb defense).
                if response.headers.get("Content-Encoding", "identity").strip().lower() not in ("", "identity"):
                    raise ValueError("encoded forward evidence response")
                # The frozen read-only producer serves JSON, never HTML or an
                # arbitrary media type. Reject unexpected responses before parsing.
                media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if media_type != "application/json":
                    raise ValueError("invalid forward evidence media type")
                chunks = []
                total = 0
                for chunk in response.iter_raw():
                    if monotonic() - started_at > MAX_RESPONSE_SECONDS:
                        raise httpx.ReadTimeout("loopback evidence response deadline exceeded")
                    total += len(chunk)
                    if total > MAX_EVIDENCE_BYTES:
                        raise ValueError("oversized forward evidence response")
                    chunks.append(chunk)
                # A peer may delay end-of-stream after sending its final JSON chunk.
                # Do not publish evidence if completion exceeded the elapsed deadline.
                if monotonic() - started_at > MAX_RESPONSE_SECONDS:
                    raise httpx.ReadTimeout("loopback evidence response deadline exceeded")
            return _validate_payload(json.loads(
                b"".join(chunks),
                object_pairs_hook=_unique_json_keys,
                parse_constant=_reject_json_constant,
                parse_float=_finite_json_float,
            ))
    except httpx.TransportError:
        # All loopback transport failures (DNS/connect/read/write/pool/protocol)
        # are data-availability failures, not evidence of model inaccuracy.
        return _inactive("unavailable", "upstream_connection_failure")
    except httpx.HTTPStatusError:
        return _inactive("unavailable", "upstream_http_failure")
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, httpx.HTTPError):
        # Bounded JSON may still contain huge numeric literals or deep nesting.
        # Treat parser/metric exhaustion as invalid upstream data, never a 500.
        return _inactive("unavailable", "invalid_upstream_evidence")
