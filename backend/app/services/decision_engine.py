"""Pure 2.0 presentation boundary; existing estimators retain numeric authority.

Technical scores never become probabilities. This adapter can veto an existing
prediction, but cannot grant permission that its upstream model denied.
"""

import math
from datetime import datetime, timezone

from app.services.predictive_features import HORIZON_SECONDS

VERSION = "orion-core-m3"
BOARD_SECTIONS = (
    "highest_statistical_edge", "liquid_research_watch",
    "higher_risk_lower_liquidity", "no_trade",
)


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _directional_diagnostics(*, model_direction, probabilities, horizon):
    """Describe exactly why the directional contract is or is not available."""
    missing = []
    if model_direction not in {"UP", "DOWN"}:
        missing.append("directional model output (model_direction=UP or DOWN)")
    valid_probabilities = all(
        value is not None and 0 <= value <= 1 for value in probabilities
    ) and abs(sum(value or 0 for value in probabilities) - 1) <= 0.00001
    if not valid_probabilities:
        missing.append("complete calibrated probability vector (P_UP, P_DOWN, P_NEUTRAL)")
    if horizon not in HORIZON_SECONDS:
        missing.append("supported prediction horizon")
    return {
        "status": "available" if not missing else "unavailable",
        "missing_inputs": missing,
        "message": (
            "Directional probability is available from the supplied model output."
            if not missing else "Directional probability was withheld because required model inputs are missing."
        ),
    }


def timestamp(value):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (TypeError, ValueError):
        return None


def recent(value, now, seconds):
    parsed = timestamp(value)
    return parsed is not None and 0 <= (now - parsed).total_seconds() <= seconds


def _observation_window_reason(value, now, seconds):
    """Classify only parseable observation times outside the causal live window."""
    parsed = timestamp(value)
    if parsed is None:
        return None
    age_seconds = (now - parsed).total_seconds()
    if age_seconds < 0:
        return "future_observation_timestamp"
    if age_seconds > seconds:
        return "stale_observation_timestamp"
    return None


def _temporal_layer_diagnostic(layer, value, now, max_age_seconds):
    """Return one stable freshness result for a required timestamped data layer."""
    parsed = timestamp(value)
    if value is None:
        status = "missing"
    elif parsed is None:
        status = "invalid"
    else:
        age_seconds = (now - parsed).total_seconds()
        status = (
            "future" if age_seconds < 0
            else "stale" if age_seconds > max_age_seconds
            else "fresh"
        )
    return {
        "status": status,
        "reason_code": (
            None if status == "fresh" else f"{status}_{layer}_timestamp"
        ),
        "timestamp": value,
        "max_age_seconds": max_age_seconds,
    }


def board_predictions(board):
    return [row for key in BOARD_SECTIONS for row in (board.get(key) or [])]


def _levels(prediction):
    levels = prediction.get("levels") or {}
    entry, targets = levels.get("entry_area"), levels.get("target_area")
    stop = number(levels.get("invalidation_level"))
    if not isinstance(entry, list) or len(entry) != 2 or not isinstance(targets, list) or not targets:
        return None
    entry, targets = [number(v) for v in entry], [number(v) for v in targets]
    if any(v is None or v <= 0 for v in [*entry, *targets, stop]):
        return None
    if entry != sorted(entry):
        return None
    if prediction.get("direction") == "UP":
        risk, reward = entry[1] - stop, min(targets) - entry[1]
        ordered = stop < entry[0] and min(targets) > entry[1]
    else:
        risk, reward = stop - entry[0], entry[0] - max(targets)
        ordered = stop > entry[1] and max(targets) < entry[0]
    if not ordered or risk <= 0 or reward <= 0:
        return None
    return {"entry_zone": entry, "invalidation": stop, "targets": sorted(targets),
            "risk_reward": reward / risk}


def decision_from_prediction(prediction, *, now=None, market_open=False):
    now = now or datetime.now(timezone.utc)
    direction = prediction.get("direction")
    horizon = prediction.get("horizon")
    warnings = list(prediction.get("blockers") or [])
    observation_time_diagnostics = prediction.get("observation_time_diagnostics")
    no_trade_reason_codes = []
    if (
        isinstance(observation_time_diagnostics, dict)
        and observation_time_diagnostics.get("status") != "ready"
    ):
        reason_code = (
            observation_time_diagnostics.get("reason_code")
            or "observation_time_unavailable"
        )
        no_trade_reason_codes.append(reason_code)
        warnings.append(
            "Point-in-time observation evidence is unavailable or invalid."
        )
    supplied_model_direction = prediction.get("model_direction")
    model_direction = (
        supplied_model_direction
        if supplied_model_direction in {"UP", "DOWN"}
        else direction if direction in {"UP", "DOWN"} else None
    )
    if model_direction is None:
        warnings.append("The statistical engine did not return a directional model output.")
    elif direction == "NO_TRADE":
        # A blocked prediction still has a valid directional estimate, but the
        # adapter must never turn that upstream NO_TRADE into a new trade.
        warnings.append("The upstream prediction withheld trade permission.")
    if prediction.get("confidence") != "validated_baseline":
        warnings.append("The model has not passed out-of-sample validation.")
    if prediction.get("liquidity_tier") not in {"A", "B"} or (number(prediction.get("liquidity_score")) or 0) < 65:
        warnings.append("This workflow requires high liquidity (Tier A or B).")
    if not market_open:
        warnings.append("The regular market session is closed or could not be verified.")
    max_age = min(120, HORIZON_SECONDS.get(horizon, 60))
    snapshot = prediction.get("feature_snapshot") or {}
    feature_input_diagnostics = {}
    feature_input_reason_codes = []
    source_event_time_reason_codes = []
    feature_source_diagnostics = {
        "stock": {"status": "not_evaluated", "features": [], "reason_codes": []},
        "market_benchmark": {
            "status": "not_evaluated", "features": [], "reason_codes": [],
        },
    }
    if prediction.get("core_validation") is not None:
        if prediction["core_validation"].get("ready") is not True:
            warnings.append("The model freshness or promotion gate failed.")
        features = snapshot.get("features") or {}
        provenance = snapshot.get("feature_provenance") or {}
        required = (
            "price_momentum", "atr_14", "realized_volatility",
            "relative_volume", "index_momentum", "relative_strength_market",
        )
        feature_sources = {
            "price_momentum": "stock",
            "atr_14": "stock",
            "realized_volatility": "stock",
            "relative_volume": "stock",
            "index_momentum": "market_benchmark",
            "relative_strength_market": "market_benchmark",
        }
        if snapshot.get("freshness_contract") != "source-specific-v2":
            feature_input_reason_codes.append("invalid_feature_freshness_contract")
        for name in required:
            metadata = provenance.get(name) or {}
            reason_codes = []
            if number(features.get(name)) is None:
                reason_codes.append(f"missing_feature_value_{name}")
            if not isinstance(provenance.get(name), dict):
                reason_codes.append(f"missing_feature_provenance_{name}")
            elif metadata.get("status") != "fresh":
                reason_codes.append(f"nonfresh_feature_provenance_{name}")
            timestamp_diagnostic = _temporal_layer_diagnostic(
                f"feature_{name}", metadata.get("as_of"), now, 120
            )
            if timestamp_diagnostic["reason_code"] is not None:
                reason_codes.append(timestamp_diagnostic["reason_code"])
            feature_input_diagnostics[name] = {
                "source": feature_sources[name],
                "value_status": (
                    "available" if number(features.get(name)) is not None
                    else "missing"
                ),
                "provenance_status": metadata.get("status"),
                "timestamp": timestamp_diagnostic,
                "reason_codes": reason_codes,
            }
            feature_input_reason_codes.extend(reason_codes)
        feature_input_reason_codes = list(dict.fromkeys(feature_input_reason_codes))
        source_event_times = snapshot.get("source_event_times") or {}
        explicit_source_times = (
            snapshot.get("source_event_time_contract") == "explicit-v1"
        )
        for source, diagnostics in feature_source_diagnostics.items():
            source_features = [
                name for name in required if feature_sources[name] == source
            ]
            source_event_time = (
                _temporal_layer_diagnostic(
                    f"{source}_source",
                    (source_event_times.get(source) or {}).get("timestamp"),
                    now,
                    (source_event_times.get(source) or {}).get(
                        "max_age_seconds", 120
                    ),
                )
                if explicit_source_times else None
            )
            if (
                source_event_time is not None
                and source_event_time["reason_code"] is not None
            ):
                source_event_time_reason_codes.append(
                    source_event_time["reason_code"]
                )
            source_reason_codes = list(dict.fromkeys([
                *(
                    ["invalid_feature_freshness_contract"]
                    if snapshot.get("freshness_contract") != "source-specific-v2"
                    else []
                ),
                *(
                    [source_event_time["reason_code"]]
                    if source_event_time is not None
                    and source_event_time["reason_code"] is not None
                    else []
                ),
                *(
                    code
                    for name in source_features
                    for code in feature_input_diagnostics[name]["reason_codes"]
                ),
            ]))
            diagnostics.update({
                "status": "blocked" if source_reason_codes else "fresh",
                "features": source_features,
                "event_time": source_event_time,
                "reason_codes": source_reason_codes,
            })
        source_event_time_reason_codes = list(dict.fromkeys(
            source_event_time_reason_codes
        ))
        no_trade_reason_codes.extend([
            *feature_input_reason_codes,
            *source_event_time_reason_codes,
        ])
        if feature_input_reason_codes or source_event_time_reason_codes:
            warnings.append("Required stock or benchmark feature evidence is stale or unavailable.")
    history_time = snapshot.get("history_timestamp") or snapshot.get("timestamp")
    data_freshness_diagnostics = {
        "prediction": _temporal_layer_diagnostic(
            "prediction", prediction.get("timestamp"), now, max_age
        ),
        "feature_bars": _temporal_layer_diagnostic(
            "feature_bars", history_time, now, max_age
        ),
        "quote": _temporal_layer_diagnostic(
            "quote", prediction.get("quote_as_of"), now, 60
        ),
    }
    data_layer_reason_codes = [
        diagnostics["reason_code"]
        for diagnostics in data_freshness_diagnostics.values()
        if diagnostics["reason_code"] is not None
    ]
    observation_window_codes = list(dict.fromkeys(
        code for code in (
            _observation_window_reason(prediction.get("timestamp"), now, max_age),
            _observation_window_reason(history_time, now, max_age),
        )
        if code is not None
    ))
    no_trade_reason_codes.extend(
        code for code in observation_window_codes
        if code not in no_trade_reason_codes
    )
    if not recent(prediction.get("timestamp"), now, max_age) or not recent(history_time, now, max_age):
        warnings.append("The price or underlying feature bars are stale or undated.")
    if not recent(prediction.get("quote_as_of"), now, 60):
        warnings.append("A current, timestamped bid/ask quote is unavailable.")
    due = timestamp(prediction.get("due_at"))
    if due is None or due <= now or horizon not in HORIZON_SECONDS:
        warnings.append("The prediction horizon has expired or is unavailable.")
    probabilities = [number(prediction.get(key)) for key in ("P_UP", "P_DOWN", "P_NEUTRAL")]
    if any(v is None or not 0 <= v <= 1 for v in probabilities) or abs(sum(v or 0 for v in probabilities) - 1) > 0.00001:
        warnings.append("The probability contract is incomplete.")
    expected = prediction.get("expected_value") or {}
    probability_contract = not any(v is None or not 0 <= v <= 1 for v in probabilities) and abs(sum(v or 0 for v in probabilities) - 1) <= 0.00001
    directional_confidence = round(number(prediction.get(f"P_{model_direction}")) * 100, 2) if probability_contract and model_direction else None
    directional_diagnostics = _directional_diagnostics(
        model_direction=model_direction,
        probabilities=probabilities,
        horizon=horizon,
    )
    decision_observation_evidence = (
        dict(observation_time_diagnostics)
        if isinstance(observation_time_diagnostics, dict)
        else {"status": "legacy_contract", "reason_code": None}
    )
    decision_observation_evidence["window_reason_codes"] = observation_window_codes
    decision_observation_evidence["freshness_status"] = (
        "outside_live_window" if observation_window_codes else "within_live_window"
    )
    directional_diagnostics["decision_evidence"] = decision_observation_evidence
    directional_diagnostics["no_trade_reason_codes"] = no_trade_reason_codes
    directional_diagnostics["data_freshness"] = data_freshness_diagnostics
    directional_diagnostics["data_layer_reason_codes"] = data_layer_reason_codes
    directional_diagnostics["feature_inputs"] = feature_input_diagnostics
    directional_diagnostics["feature_input_reason_codes"] = feature_input_reason_codes
    directional_diagnostics["feature_sources"] = feature_source_diagnostics
    directional_diagnostics["source_event_time_reason_codes"] = (
        source_event_time_reason_codes
    )
    ev = number(expected.get("EV_LONG_bps" if model_direction == "UP" else "EV_SHORT_bps"))
    cost = number((prediction.get("execution_costs") or {}).get("round_trip_cost_bps"))
    if ev is None or ev <= 0 or cost is None or cost < 0:
        warnings.append("A positive edge after known execution costs is required.")
    levels = _levels(prediction)
    if not levels or levels["risk_reward"] < 1.5:
        warnings.append("A coherent entry, invalidation and target with at least 1.5R is required.")
    reference_price = number(prediction.get("price"))
    if reference_price is None or reference_price <= 0:
        warnings.append("A valid reference price is unavailable.")
    elif levels and not levels["entry_zone"][0] <= reference_price <= levels["entry_zone"][1]:
        warnings.append("The reference price is outside the entry zone.")
    warnings = list(dict.fromkeys(warnings))
    actionable = not warnings
    directional_result = {
        "status": directional_diagnostics["status"],
        "direction": model_direction,
        "probability_up": probabilities[0],
        "probability_down": probabilities[1],
        "probability_neutral": probabilities[2],
        "directional_confidence": directional_confidence,
        "model_agreement": (prediction.get("strategy_consensus") or {}).get("agreement_score"),
        "setup_quality": (prediction.get("opportunity_score") or {}).get("score"),
        "liquidity_score": prediction.get("liquidity_score"),
        "expected_horizon": horizon,
        "reasons": [prediction.get("short_explanation") or "Deterministic model evidence evaluated."],
        "warnings": warnings,
        "diagnostics": directional_diagnostics,
    }
    return {
        "version": VERSION, "ticker": prediction.get("ticker"),
        "company_name": prediction.get("company_name"),
        "timestamp": prediction.get("timestamp"), "evaluated_at": now.isoformat(),
        "price": number(prediction.get("price")),
        "decision": "BUY" if actionable and direction == "UP" else "AVOID" if actionable else "WAIT",
        "direction": "LONG" if actionable and direction == "UP" else "SHORT" if actionable else "WAIT",
        "status": "qualified" if actionable else "no_trade", "actionable": actionable,
        # `confidence` remains trade permission confidence for compatibility;
        # `directional_confidence` is the model estimate even when a safety
        # gate correctly turns the final decision into WAIT.
        "confidence": round(number(prediction[f"P_{model_direction}"]) * 100, 2) if actionable and model_direction else None,
        "directional_confidence": directional_confidence,
        "probability_up": probabilities[0], "probability_down": probabilities[1],
        "probability_neutral": probabilities[2], "model_direction": model_direction,
        "confidence_kind": "calibrated_directional_probability" if directional_confidence is not None else "unavailable",
        "entry_zone": levels["entry_zone"] if actionable else None,
        "invalidation": levels["invalidation"] if actionable else None,
        "targets": levels["targets"] if actionable else [],
        "risk_reward": round(levels["risk_reward"], 2) if actionable else None,
        "expected_move": number(expected.get("predicted_return_percent")),
        "timeframe": horizon, "expected_horizon": horizon,
        "expires_at": prediction.get("due_at"),
        "liquidity_score": prediction.get("liquidity_score"),
        "liquidity_tier": prediction.get("liquidity_tier"),
        "setup_quality": (prediction.get("opportunity_score") or {}).get("score"),
        "market_regime": (prediction.get("market_regime") or {}).get("label"),
        "reasons": [prediction.get("short_explanation") or "Deterministic model evidence evaluated."],
        "warnings": warnings,
        "no_trade_reason_codes": no_trade_reason_codes,
        "data_layer_reason_codes": data_layer_reason_codes,
        "data_freshness_diagnostics": data_freshness_diagnostics,
        "feature_input_reason_codes": feature_input_reason_codes,
        "feature_input_diagnostics": feature_input_diagnostics,
        "feature_source_diagnostics": feature_source_diagnostics,
        "source_event_time_reason_codes": source_event_time_reason_codes,
        "model_agreement": (prediction.get("strategy_consensus") or {}).get("agreement_score"),
        "model_outputs": prediction,
        "confidence_unavailable_reasons": directional_diagnostics["missing_inputs"],
        "directional_diagnostics": directional_diagnostics,
        "directional_result": directional_result,
        "prediction_id": prediction.get("prediction_id"),
        "evidence": None,
        "semantics": "Research only. SHORT/AVOID is bearish context, not permission to open a short. Confidence is not a target-hit probability. Levels are ATR-derived scenarios, not forecasts.",
    }


def _ranking(row):
    return (0 if row.get("liquidity_tier") == "A" else 1,
            -(number(row.get("liquidity_score")) or 0),
            -(number(row.get("setup_quality")) or 0))


def decisions_from_board(board, *, now=None, market_open=False):
    rows = [decision_from_prediction(p, now=now, market_open=market_open)
            for p in board_predictions(board)]
    # Contradictory approved horizons may not be hidden by selecting the best one.
    by_ticker = {}
    for row in rows:
        if row["actionable"]:
            by_ticker.setdefault(row["ticker"], set()).add(row["direction"])
    for row in rows:
        conflicting = len(by_ticker.get(row["ticker"], set())) > 1
        incomplete = any(item.get("ticker") == row["ticker"] for item in (board.get("unavailable_predictions") or []))
        if conflicting or incomplete:
            row.update(actionable=False, decision="WAIT", direction="WAIT", status="no_trade",
                       confidence=None, confidence_kind=("calibrated_directional_probability" if row.get("directional_confidence") is not None else "unavailable"), entry_zone=None,
                       invalidation=None, targets=[], risk_reward=None, expected_move=None)
            row["warnings"].append("Validated horizons disagree on direction; wait for alignment." if conflicting else "A requested horizon for this ticker is unavailable; wait for complete evidence.")
            if row.get("directional_result"):
                row["directional_result"] = {
                    **row["directional_result"], "warnings": row["warnings"],
                }
    return sorted(rows, key=_ranking)


def today_from_board(board, *, now=None, market_open=False):
    rows = decisions_from_board(board, now=now, market_open=market_open)
    selected, seen = [], set()
    for row in rows:
        if row["actionable"] and row["ticker"] not in seen:
            selected.append(row)
            seen.add(row["ticker"])
        if len(selected) == 5:
            break
    incomplete = bool(board.get("partial_failure"))
    return {
        "version": VERSION, "status": "partial" if incomplete else "ready",
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "opportunities": selected, "market_open": market_open,
        "message": "High-liquidity setups worth a closer look." if selected else (
            "No qualifying setups in the available results. Some data was unavailable."
            if incomplete else "No high-quality setups detected right now."
        ),
        "coverage": {"liquidity_candidates_ranked": board.get("liquidity_candidates_ranked", 0),
                     "predictions_evaluated": len(rows), "unique_tickers": len({r["ticker"] for r in rows})},
        "warnings": list(board.get("errors") or []),
        "unavailable_predictions": board.get("unavailable_predictions") or [],
        "radar": board.get("radar") or {},
        "orion_prime": board.get("orion_prime") or [],
        "scope": "Bounded sample of the connected tradable universe; not every listed stock.",
        "_final_decisions": rows,
    }


def technical_decision(ticker, research=None, *, company_name=None, warnings=None, directional_diagnostics=None):
    research = research or {}
    evidence = research.get("strategy_analysis") or {}
    sufficient = (evidence.get("data_quality") or {}).get("sufficient") is True
    top = evidence.get("top_setup") or {}
    diagnostics = dict(directional_diagnostics or {})
    missing_inputs = list(diagnostics.get("missing_inputs") or [])
    if not sufficient and "sufficient point-in-time feature history" not in missing_inputs:
        missing_inputs.insert(0, "sufficient point-in-time feature history")
    if "validated calibrated directional model" not in missing_inputs:
        missing_inputs.append("validated calibrated directional model")
    if "complete calibrated probability vector (P_UP, P_DOWN, P_NEUTRAL)" not in missing_inputs:
        missing_inputs.append("complete calibrated probability vector (P_UP, P_DOWN, P_NEUTRAL)")
    diagnostics.update({
        "status": "unavailable",
        "missing_inputs": missing_inputs,
        "message": diagnostics.get("message") or "Directional probability was withheld because required model inputs are missing.",
    })
    reasons = [top.get("summary") or ("No aligned technical setup in the supplied history." if sufficient else "Sufficient market evidence is unavailable.")]
    all_warnings = [*(warnings or []), "Technical rule scores are not calibrated probabilities; no validated trade plan is available."]
    return {
        "version": VERSION, "ticker": ticker, "company_name": company_name,
        "timestamp": (evidence.get("data_quality") or {}).get("latest_daily_bar"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "price": number((research.get("quote") or {}).get("price")),
        "decision": "WAIT", "direction": "WAIT", "actionable": False,
        "status": "research_only" if sufficient else "unavailable",
        "confidence": None, "directional_confidence": None,
        "probability_up": None, "probability_down": None,
        "probability_neutral": None, "model_direction": None,
        "confidence_kind": "unavailable",
        "entry_zone": None, "invalidation": None, "targets": [], "risk_reward": None,
        "expected_move": None, "timeframe": None, "expires_at": None,
        "liquidity_score": None, "liquidity_tier": None, "setup_quality": top.get("score"),
        "model_agreement": None, "expected_horizon": None,
        "market_regime": (evidence.get("market_regime") or {}).get("summary"),
        "reasons": reasons,
        "warnings": all_warnings,
        "confidence_unavailable_reasons": diagnostics["missing_inputs"],
        "directional_diagnostics": diagnostics,
        "model_outputs": None, "prediction_id": None, "evidence": research,
        "semantics": "Historical technical context only. Fetched-at time is not a live exchange quote timestamp.",
        "directional_result": {
            "status": diagnostics["status"], "direction": None,
            "probability_up": None, "probability_down": None,
            "probability_neutral": None,
            "directional_confidence": None, "model_agreement": None,
            "setup_quality": top.get("score"), "liquidity_score": None,
            "expected_horizon": None, "reasons": reasons,
            "warnings": all_warnings, "diagnostics": diagnostics,
        },
    }
