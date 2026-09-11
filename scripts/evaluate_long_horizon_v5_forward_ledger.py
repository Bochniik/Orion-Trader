from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from evals.long_horizon_challenger_gate import (
    LONG_HORIZONS,
    PREREGISTERED_CUTOFF_UTC,
    evaluate_long_horizon_candidate,
)

LEDGER_CONTRACT = "orion-cloud-shadow-evidence-ledger-v1"
REPORT_CONTRACT = "orion-long-horizon-v5-forward-decision-v1"
INCUMBENT_ENGINE = "regular_hours_v3_1"
CHALLENGER_ENGINE = "long-horizon-v5-20260911-a"
MIN_OBSERVATIONS = 80
MIN_SESSIONS = 8
BOOTSTRAP_SAMPLES = 2000
SEED = 20260911


def _parse_timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _ledger_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pair_key(record: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("symbol") or "").upper().strip(),
        str(record.get("horizon") or "").strip(),
        _parse_timestamp(record.get("prediction_time_utc")).isoformat(),
        _parse_timestamp(record.get("target_time_utc")).isoformat(),
    )


def _role_for_record(record: Mapping[str, Any]) -> str | None:
    engine = str(record.get("engine") or "")
    lineage = record.get("lineage") or {}
    role = str(lineage.get("paired_role") or "") if isinstance(lineage, Mapping) else ""
    expected = "incumbent" if engine == INCUMBENT_ENGINE else "challenger" if engine == CHALLENGER_ENGINE else None
    if expected is None:
        return None
    if role and role != expected:
        raise ValueError(f"Paired role/engine mismatch for {engine}: {role}")
    return expected


def _validate_pair(incumbent: Mapping[str, Any], challenger: Mapping[str, Any]) -> None:
    if int(incumbent.get("actual_up")) != int(challenger.get("actual_up")):
        raise ValueError(f"Outcome mismatch for paired record {_pair_key(incumbent)}")
    for field in ("base_price", "outcome_price", "realized_return_pct"):
        if float(incumbent.get(field)) != float(challenger.get(field)):
            raise ValueError(f"Settlement mismatch in {field} for paired record {_pair_key(incumbent)}")


def collect_pairs(ledger: Mapping[str, Any]) -> dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]]:
    if ledger.get("contract") != LEDGER_CONTRACT:
        raise ValueError(f"Unsupported evidence ledger contract: {ledger.get('contract')}")
    records = ledger.get("records") or []
    if not isinstance(records, list):
        raise ValueError("Ledger records must be a list")

    cutoff = _parse_timestamp(PREREGISTERED_CUTOFF_UTC)
    buckets: dict[tuple[str, str, str, str], dict[str, Mapping[str, Any]]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Ledger contains a non-object record")
        role = _role_for_record(record)
        if role is None:
            continue
        horizon = str(record.get("horizon") or "")
        if horizon not in LONG_HORIZONS:
            raise ValueError(f"Frozen forward ledger contains unsupported horizon for V5 pair: {horizon}")
        key = _pair_key(record)
        if not key[0]:
            raise ValueError("Frozen forward ledger contains a record without symbol")
        prediction_time = _parse_timestamp(record.get("prediction_time_utc"))
        if prediction_time < cutoff:
            raise ValueError(f"Pre-registration observation in forward ledger: {prediction_time.isoformat()}")
        probability = float(record.get("probability_up"))
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"Invalid probability_up for {key}: {probability}")
        slot = buckets.setdefault(key, {})
        if role in slot:
            prior = slot[role]
            if str(prior.get("material_sha256")) != str(record.get("material_sha256")):
                raise ValueError(f"Conflicting duplicate {role} record for {key}")
            continue
        slot[role] = record

    incomplete = [key for key, slot in buckets.items() if set(slot) != {"incumbent", "challenger"}]
    if incomplete:
        preview = ", ".join(str(key) for key in incomplete[:3])
        raise ValueError(f"Incomplete incumbent/challenger pairs in forward ledger ({len(incomplete)}): {preview}")

    result = {horizon: [] for horizon in LONG_HORIZONS}
    for key in sorted(buckets, key=lambda item: (item[2], item[0], item[1], item[3])):
        slot = buckets[key]
        incumbent = slot["incumbent"]
        challenger = slot["challenger"]
        _validate_pair(incumbent, challenger)
        result[key[1]].append((incumbent, challenger))
    return result


def readiness(pairs: Mapping[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]]) -> dict[str, Any]:
    horizons: dict[str, Any] = {}
    all_ready = True
    for horizon in LONG_HORIZONS:
        rows = pairs.get(horizon) or []
        sessions = {_parse_timestamp(pair[0].get("prediction_time_utc")).date().isoformat() for pair in rows}
        ready = len(rows) >= MIN_OBSERVATIONS and len(sessions) >= MIN_SESSIONS
        all_ready = all_ready and ready
        horizons[horizon] = {
            "ready": ready,
            "paired_observations": len(rows),
            "minimum_observations": MIN_OBSERVATIONS,
            "observations_remaining": max(0, MIN_OBSERVATIONS - len(rows)),
            "distinct_sessions": len(sessions),
            "minimum_sessions": MIN_SESSIONS,
            "sessions_remaining": max(0, MIN_SESSIONS - len(sessions)),
        }
    return {"all_required_horizons_ready": all_ready, "horizons": horizons}


def _tournament_reports(
    pairs: Mapping[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    incumbent_records: dict[str, list[dict[str, Any]]] = {h: [] for h in LONG_HORIZONS}
    challenger_records: dict[str, list[dict[str, Any]]] = {h: [] for h in LONG_HORIZONS}
    for horizon in LONG_HORIZONS:
        for incumbent, challenger in pairs.get(horizon) or []:
            shared = {
                "symbol": str(incumbent["symbol"]).upper(),
                "timestamp": _parse_timestamp(incumbent["prediction_time_utc"]).isoformat(),
                "actual_up": int(incumbent["actual_up"]),
            }
            incumbent_records[horizon].append({**shared, "p_up": float(incumbent["probability_up"]) * 100.0})
            challenger_records[horizon].append({**shared, "p_up": float(challenger["probability_up"]) * 100.0})
    return {"prediction_records": incumbent_records}, {"prediction_records": challenger_records}


def evaluate_ledger(path: Path) -> dict[str, Any]:
    ledger = json.loads(path.read_text(encoding="utf-8"))
    pairs = collect_pairs(ledger)
    sample_readiness = readiness(pairs)
    base = {
        "contract": REPORT_CONTRACT,
        "research_only": True,
        "runtime_modified": False,
        "promotion_allowed": False,
        "challenger_design_id": CHALLENGER_ENGINE,
        "incumbent_engine": INCUMBENT_ENGINE,
        "pre_registered_cutoff_utc": PREREGISTERED_CUTOFF_UTC,
        "ledger_sha256": _ledger_sha256(path),
        "score_blind_until_mature": True,
        "forward_sample_readiness": sample_readiness,
    }
    if not sample_readiness["all_required_horizons_ready"]:
        return {
            **base,
            "decision_grade": False,
            "metrics_exposed": False,
            "research_conclusion": "forward_holdout_collecting_evidence",
        }

    incumbent, challenger = _tournament_reports(pairs)
    decision = evaluate_long_horizon_candidate(
        incumbent,
        challenger,
        evidence_mode="forward_holdout",
        min_observations=MIN_OBSERVATIONS,
        min_sessions=MIN_SESSIONS,
        bootstrap_samples=BOOTSTRAP_SAMPLES,
        seed=SEED,
    )
    return {
        **base,
        "decision_grade": True,
        "metrics_exposed": True,
        "research_conclusion": decision["research_conclusion"],
        "forward_research_eligible": bool(decision["forward_research_eligible"]),
        "paired_tournament": decision["paired_tournament"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, score-blind-until-mature V5 forward decision report from the dedicated evidence ledger."
    )
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backend/data/cloud_shadow/long_horizon_v5/evidence/decision.json"))
    args = parser.parse_args()
    result = evaluate_ledger(args.ledger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "decision_grade": result["decision_grade"],
        "metrics_exposed": result["metrics_exposed"],
        "research_conclusion": result["research_conclusion"],
        "forward_sample_readiness": result["forward_sample_readiness"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())