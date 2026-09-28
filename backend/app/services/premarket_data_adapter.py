from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Dict, Optional

import pandas as pd

from app.services.premarket_scanner_engine import analyze_premarket
from app.services.premarket_entry_decision_engine import evaluate_premarket_entry
from app.services.market_integrity_engine import analyze_market_integrity
from app.services.premarket_hierarchical_runtime import (
    MODEL_VERSION as HIERARCHICAL_MODEL_VERSION,
    predict_gated_hierarchical_outlook,
)


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def alpaca_bars_to_frame(rows: Any) -> Optional[pd.DataFrame]:
    """Convert provider-native Alpaca bars to Orion OHLCV."""
    if not isinstance(rows, list) or not rows:
        return None

    parsed = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        stamp = row.get("t")
        if not stamp:
            continue

        values = {
            "Open": _finite(row.get("o")),
            "High": _finite(row.get("h")),
            "Low": _finite(row.get("l")),
            "Close": _finite(row.get("c")),
            "Volume": _finite(row.get("v")),
        }

        if (
            any(values[key] is None for key in values)
            or any(values[key] <= 0 for key in ("Open", "High", "Low", "Close"))
            or values["Volume"] < 0
        ):
            continue

        parsed.append({"timestamp": stamp, **values})

    if not parsed:
        return None

    frame = pd.DataFrame(parsed)
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
    )
    frame = frame.dropna(subset=["timestamp"])

    if frame.empty:
        return None

    frame = (
        frame.drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .set_index("timestamp")
    )

    return frame[["Open", "High", "Low", "Close", "Volume"]]


def previous_completed_close(
    history: Any,
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    if (
        not isinstance(history, pd.DataFrame)
        or history.empty
        or "Close" not in history.columns
    ):
        return None

    frame = history.copy()

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce")

    frame = frame[~frame.index.isna()].sort_index()

    if frame.empty:
        return None

    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    ny_today = pd.Timestamp(now).tz_convert("America/New_York").date()
    completed = []

    for index, row in frame.iterrows():
        stamp = pd.Timestamp(index)

        if stamp.tzinfo is None:
            row_date = stamp.date()
        else:
            row_date = stamp.tz_convert("America/New_York").date()

        if row_date >= ny_today:
            continue

        close = _finite(row.get("Close"))

        if close is not None and close > 0:
            completed.append(close)

    return completed[-1] if completed else None


def _predictive_unavailable(reason: str) -> Dict[str, Any]:
    return {
        "available": False,
        "actionable": False,
        "model_version": HIERARCHICAL_MODEL_VERSION,
        "reason": reason,
        "signals": {},
    }


class PremarketDataAdapter:
    """Provider bridge for Orion premarket analysis.

    Fallback order:
      1. current-day IEX minute bars, if actually available
      2. delayed consolidated SIP historical minute bars
      3. freshness-validated point snapshot/latest bar
      4. unavailable

    A single point observation never becomes fake minute history.
    """

    def __init__(self, broker, market_data):
        self.broker = broker
        self.market = market_data

    def _daily_history(self, symbol: str):
        return self.market.get_price_history(
            symbol,
            period="1mo",
            interval="1d",
        )

    def _resolve_previous_close(
        self,
        symbol: str,
        *,
        now: datetime,
        previous_close_override: Any = None,
    ) -> tuple[Optional[float], list]:
        warnings = []

        override = _finite(previous_close_override)
        if override is not None and override > 0:
            return override, warnings

        try:
            history = self._daily_history(symbol)
            close = previous_completed_close(history, now=now)
            return close, warnings
        except Exception as exc:
            warnings.append(
                f"Daily previous-close lookup unavailable: {type(exc).__name__}"
            )
            return None, warnings

    @staticmethod
    def _analysis_payload(
        *,
        symbol: str,
        analysis: Dict[str, Any],
        data_mode: str,
        feed: str,
        delayed: bool,
        minute_frame: pd.DataFrame,
        provider_payload: Dict[str, Any],
        warnings: list,
        now: datetime,
        news_score: Any = None,
        average_dollar_volume: Any = None,
    ) -> Dict[str, Any]:
        payload = {
            "ticker": symbol,
            "session": "premarket",
            "analysis_status": "full_premarket_analysis",
            "data_mode": data_mode,
            "provider": provider_payload.get("provider") or "alpaca",
            "feed": feed,
            "delayed": delayed,
            "safe_delay_seconds": provider_payload.get("safe_delay_seconds"),
            "delay_minutes_nominal": provider_payload.get("delay_minutes_nominal"),
            "full_intraday_history": True,
            "minute_bar_count": len(minute_frame),
            "previous_close": analysis.get("previous_close"),
            "premarket_open": analysis.get("premarket_open"),
            "premarket_price": analysis.get("premarket_price"),
            "premarket_high": analysis.get("premarket_high"),
            "premarket_low": analysis.get("premarket_low"),
            "premarket_vwap": analysis.get("premarket_vwap"),
            "gap_pct": analysis.get("gap_pct"),
            "premarket_return_pct": analysis.get("premarket_return_pct"),
            "range_pct": analysis.get("range_pct"),
            "vwap_position_pct": analysis.get("vwap_position_pct"),
            "distance_from_premarket_high_pct": analysis.get(
                "distance_from_premarket_high_pct"
            ),
            "distance_from_premarket_low_pct": analysis.get(
                "distance_from_premarket_low_pct"
            ),
            "trend_slope_pct_per_bar": analysis.get(
                "trend_slope_pct_per_bar"
            ),
            "premarket_volume": analysis.get("premarket_volume"),
            "premarket_dollar_volume": analysis.get(
                "premarket_dollar_volume"
            ),
            "relative_premarket_volume": analysis.get(
                "relative_premarket_volume"
            ),
            "volume_acceleration": analysis.get("volume_acceleration"),
            "premarket_score": analysis.get("score"),
            "premarket_label": analysis.get("label"),
            "direction": analysis.get("direction"),
            "eligible": analysis.get("eligible"),
            "setup_state": analysis.get("setup_state"),
            "confirmation_required": True,
            "invalidation_reference": analysis.get(
                "invalidation_reference"
            ),
            "data_timestamp": analysis.get("data_timestamp"),
            "analysis": analysis,
            "warnings": list(dict.fromkeys(
                warnings
                + list(analysis.get("warnings") or [])
                + list(provider_payload.get("limitations") or [])
            )),
            "as_of": provider_payload.get("as_of") or now.isoformat(),
        }

        # Predict against the newest bar actually present in the feature frame.
        # For delayed SIP this keeps live feature semantics aligned with the
        # timestamps used by the historical training snapshots.
        predictive_as_of = minute_frame.index[-1] if not minute_frame.empty else None
        try:
            payload["predictive_outlook"] = predict_gated_hierarchical_outlook(
                minute_frame,
                previous_close=analysis.get("previous_close"),
                feed=feed,
                as_of=predictive_as_of,
            )
        except Exception as exc:
            payload["predictive_outlook"] = _predictive_unavailable(
                f"hierarchical_runtime_error:{type(exc).__name__}"
            )

        payload["market_integrity"] = analyze_market_integrity(
            symbol,
            minute_frame,
            average_dollar_volume=average_dollar_volume,
            news_score=news_score,
            now=now,
        )
        payload["premarket_entry_decision"] = evaluate_premarket_entry(payload)
        return payload

    def build(
        self,
        user_id: str,
        ticker: str,
        *,
        now: Optional[datetime] = None,
        news_score: Any = None,
        market_score: Any = None,
        sector_score: Any = None,
        thematic_score: Any = None,
        average_premarket_volume: Any = None,
        previous_close_override: Any = None,
        average_dollar_volume: Any = None,
    ) -> Dict[str, Any]:
        symbol = str(ticker or "").strip().upper()

        if not symbol:
            raise ValueError("ticker is required")

        now = now or datetime.now(timezone.utc)

        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        warnings = []
        provider_errors = []

        previous_close, close_warnings = self._resolve_previous_close(
            symbol,
            now=now,
            previous_close_override=previous_close_override,
        )
        warnings.extend(close_warnings)

        # --------------------------------------------------------------
        # 1) Current IEX minute history, if the account/provider supplies it.
        # --------------------------------------------------------------
        try:
            iex_payload = self.broker.premarket_bars(
                user_id,
                [symbol],
                now=now,
                feed="iex",
                timeframe="1Min",
            )
        except Exception as exc:
            iex_payload = {
                "bars": {},
                "provider": "alpaca",
                "feed": "iex",
                "limitations": [],
            }
            provider_errors.append(
                f"IEX premarket minute bars unavailable: {type(exc).__name__}"
            )

        iex_rows = (
            (iex_payload.get("bars") or {}).get(symbol, [])
            if isinstance(iex_payload, dict)
            else []
        )
        iex_frame = alpaca_bars_to_frame(iex_rows)

        if iex_frame is not None and len(iex_frame) >= 5:
            analysis = analyze_premarket(
                symbol,
                iex_frame,
                previous_close=previous_close,
                average_premarket_volume=average_premarket_volume,
                news_score=news_score,
                market_score=market_score,
                sector_score=sector_score,
                thematic_score=thematic_score,
                now=now,
            )

            payload = self._analysis_payload(
                symbol=symbol,
                analysis=analysis,
                data_mode="iex_minute_history",
                feed="iex",
                delayed=False,
                minute_frame=iex_frame,
                provider_payload=iex_payload,
                warnings=warnings + provider_errors,
                now=now,
                news_score=news_score,
                average_dollar_volume=average_dollar_volume,
            )

            # The validated hierarchical directional model is SIP-trained and
            # correctly refuses IEX input. Do not let the fresher IEX setup
            # path short-circuit a model-compatible delayed SIP forecast.
            predictive = payload.get("predictive_outlook") or {}
            if predictive.get("reason") == "training_feed_mismatch_requires_sip":
                try:
                    predictive_sip_payload = self.broker.delayed_premarket_bars(
                        user_id,
                        [symbol],
                        now=now,
                        timeframe="1Min",
                        safe_delay_seconds=960,
                    )
                    predictive_sip_rows = (
                        (predictive_sip_payload.get("bars") or {}).get(symbol, [])
                        if isinstance(predictive_sip_payload, dict)
                        else []
                    )
                    predictive_sip_frame = alpaca_bars_to_frame(
                        predictive_sip_rows
                    )
                    if (
                        predictive_sip_frame is not None
                        and len(predictive_sip_frame) >= 5
                    ):
                        predictive_as_of = predictive_sip_frame.index[-1]
                        payload["predictive_outlook"] = (
                            predict_gated_hierarchical_outlook(
                                predictive_sip_frame,
                                previous_close=analysis.get("previous_close"),
                                feed="sip",
                                as_of=predictive_as_of,
                            )
                        )
                        payload["predictive_feed"] = "sip"
                        payload["predictive_delayed"] = True
                        payload["predictive_as_of"] = (
                            predictive_as_of.isoformat()
                        )
                        payload["predictive_delay_minutes_nominal"] = (
                            predictive_sip_payload.get(
                                "delay_minutes_nominal"
                            )
                        )
                        payload["warnings"] = list(dict.fromkeys(
                            list(payload.get("warnings") or [])
                            + list(
                                predictive_sip_payload.get("limitations") or []
                            )
                        ))
                except Exception as exc:
                    payload["warnings"] = list(dict.fromkeys(
                        list(payload.get("warnings") or [])
                        + [
                            "Model-compatible delayed SIP forecast fallback "
                            f"unavailable: {type(exc).__name__}"
                        ]
                    ))

            return payload

        # --------------------------------------------------------------
        # 2) Delayed historical consolidated SIP minute history.
        # --------------------------------------------------------------
        try:
            sip_payload = self.broker.delayed_premarket_bars(
                user_id,
                [symbol],
                now=now,
                timeframe="1Min",
                safe_delay_seconds=960,
            )
        except Exception as exc:
            sip_payload = {
                "bars": {},
                "provider": "alpaca",
                "feed": "sip",
                "limitations": [],
                "available": False,
            }
            provider_errors.append(
                f"Delayed SIP premarket history unavailable: {type(exc).__name__}"
            )

        sip_rows = (
            (sip_payload.get("bars") or {}).get(symbol, [])
            if isinstance(sip_payload, dict)
            else []
        )
        sip_frame = alpaca_bars_to_frame(sip_rows)

        if sip_frame is not None and len(sip_frame) >= 5:
            analysis = analyze_premarket(
                symbol,
                sip_frame,
                previous_close=previous_close,
                average_premarket_volume=average_premarket_volume,
                news_score=news_score,
                market_score=market_score,
                sector_score=sector_score,
                thematic_score=thematic_score,
                now=now,
            )

            return self._analysis_payload(
                symbol=symbol,
                analysis=analysis,
                data_mode="delayed_sip_minute_history",
                feed="sip",
                delayed=True,
                minute_frame=sip_frame,
                provider_payload=sip_payload,
                warnings=warnings + provider_errors,
                now=now,
                news_score=news_score,
                average_dollar_volume=average_dollar_volume,
            )

        # --------------------------------------------------------------
        # 3) Point fallback. No full score from one point.
        # --------------------------------------------------------------
        try:
            fallback = self.broker.premarket_snapshot_fallback(
                user_id,
                [symbol],
                now=now,
            )
        except Exception as exc:
            fallback = {
                "provider": "alpaca",
                "mode": "unavailable",
                "symbols": {},
                "warnings": [],
            }
            provider_errors.append(
                f"Premarket point fallback unavailable: {type(exc).__name__}"
            )

        observation = (
            (fallback.get("symbols") or {}).get(symbol)
            if isinstance(fallback, dict)
            else None
        )

        if isinstance(observation, dict):
            price = _finite(observation.get("price"))
            gap_pct = (
                ((price / previous_close) - 1.0) * 100.0
                if price is not None and previous_close
                else None
            )

            delayed = observation.get("delayed") is True
            data_mode = fallback.get("mode") or "point_snapshot"

            warnings.extend([
                "Full usable premarket minute history is unavailable.",
                "No full premarket setup score is produced from a single point observation.",
            ])

            payload = {
                "ticker": symbol,
                "session": "premarket",
                "analysis_status": "limited_point_snapshot",
                "data_mode": data_mode,
                "provider": fallback.get("provider") or "alpaca",
                "feed": "delayed_sip" if delayed else "iex",
                "delayed": delayed,
                "delay_minutes_nominal": fallback.get(
                    "delay_minutes_nominal"
                ),
                "full_intraday_history": False,
                "previous_close": previous_close,
                "premarket_open": None,
                "premarket_price": price,
                "premarket_high": None,
                "premarket_low": None,
                "premarket_vwap": None,
                "price_timestamp": observation.get("timestamp"),
                "price_age_seconds": observation.get("age_seconds"),
                "gap_pct": round(gap_pct, 4) if gap_pct is not None else None,
                "premarket_score": None,
                "premarket_label": None,
                "direction": None,
                "eligible": False,
                "setup_state": "WAIT_FOR_OPEN_CONFIRMATION",
                "confirmation_required": True,
                "invalidation_reference": None,
                "missing_for_full_analysis": [
                    "usable premarket minute OHLCV history",
                    "premarket trend",
                    "premarket range",
                    "premarket VWAP",
                    "volume acceleration",
                ],
                "warnings": list(dict.fromkeys(
                    warnings
                    + provider_errors
                    + list(fallback.get("warnings") or [])
                    + list(iex_payload.get("limitations") or [])
                    + list(sip_payload.get("limitations") or [])
                )),
                "as_of": fallback.get("as_of") or now.isoformat(),
                "predictive_outlook": _predictive_unavailable(
                    "full_sip_minute_history_required"
                ),
            }
            payload["market_integrity"] = {
                "ticker": symbol,
                "available": False,
                "market_integrity_risk": None,
                "market_integrity_score": None,
                "directional_distortion": None,
                "state": "INSUFFICIENT_DATA",
                "reasons": [],
                "warnings": [
                    "Full minute OHLCV history is required for market-integrity analysis."
                ],
            }
            payload["premarket_entry_decision"] = evaluate_premarket_entry(payload)
            return payload

        payload = {
            "ticker": symbol,
            "session": "premarket",
            "analysis_status": "unavailable",
            "data_mode": "unavailable",
            "provider": "alpaca",
            "feed": None,
            "delayed": None,
            "full_intraday_history": False,
            "previous_close": previous_close,
            "premarket_price": None,
            "gap_pct": None,
            "premarket_score": None,
            "direction": None,
            "eligible": False,
            "setup_state": "WAIT_FOR_OPEN_CONFIRMATION",
            "confirmation_required": True,
            "invalidation_reference": None,
            "missing_for_full_analysis": [
                "fresh current-day premarket observation",
                "usable premarket minute OHLCV history",
            ],
            "warnings": list(dict.fromkeys(
                warnings
                + provider_errors
                + list(fallback.get("warnings") or [])
                + list(iex_payload.get("limitations") or [])
                + list(sip_payload.get("limitations") or [])
            )),
            "as_of": now.isoformat(),
            "predictive_outlook": _predictive_unavailable(
                "full_sip_minute_history_required"
            ),
        }
        payload["market_integrity"] = {
            "ticker": symbol,
            "available": False,
            "market_integrity_risk": None,
            "market_integrity_score": None,
            "directional_distortion": None,
            "state": "INSUFFICIENT_DATA",
            "reasons": [],
            "warnings": [
                "No usable minute OHLCV history is available for market-integrity analysis."
            ],
        }
        payload["premarket_entry_decision"] = evaluate_premarket_entry(payload)
        return payload


if __name__ == "__main__":
    # Deterministic test for delayed SIP minute-history path.
    class FakeBroker:
        def premarket_bars(self, user_id, symbols, **kwargs):
            return {"bars": {symbols[0]: []}, "limitations": []}

        def delayed_premarket_bars(self, user_id, symbols, **kwargs):
            rows = []
            for i in range(10):
                rows.append({
                    "t": f"2026-09-04T11:{i:02d}:00Z",
                    "o": 230.0 + i * 0.1,
                    "h": 230.2 + i * 0.1,
                    "l": 229.9 + i * 0.1,
                    "c": 230.1 + i * 0.1,
                    "v": 100000 + i * 10000,
                })
            return {
                "bars": {symbols[0]: rows},
                "provider": "alpaca",
                "feed": "sip",
                "delayed": True,
                "safe_delay_seconds": 960,
                "delay_minutes_nominal": 16,
                "as_of": "2026-09-04T11:09:00+00:00",
                "limitations": [],
            }

        def premarket_snapshot_fallback(self, user_id, symbols, **kwargs):
            return {"symbols": {}, "warnings": []}

    class FakeMarket:
        def get_price_history(self, symbol, period="1mo", interval="1d"):
            return pd.DataFrame()

    adapter = PremarketDataAdapter(FakeBroker(), FakeMarket())
    result = adapter.build(
        "demo",
        "NVDA",
        now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
        previous_close_override=228.54,
        news_score=0.2,
        market_score=0.3,
        sector_score=0.25,
    )

    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))