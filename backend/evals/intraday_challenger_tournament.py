from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

_EVALS_DIR = str(Path(__file__).resolve().parent)
if _EVALS_DIR not in sys.path:
    sys.path.insert(0, _EVALS_DIR)
from adaptive_challenger_registry import assert_forward_evidence_eligible, validate_registration

HORIZONS = ("30m", "1h", "3h", "5h")
MIN_PAIRED_OBSERVATIONS = 80
MIN_DISTINCT_SESSIONS = 8
BOOTSTRAP_SAMPLES = 2000
DEFAULT_SEED = 20260910
SEMANTICS = ("Offline paired challenger tournament. Incumbent and challenger are scored only on the same symbol/timestamped out-of-sample observations. Session-block bootstrap resamples whole trading days, preserving intraday dependence. A challenger is research-eligible only when coverage is sufficient, proper-score improvement is positive and stable, and immutable preregistration proves every challenger observation is strictly post-cutoff.")

@dataclass(frozen=True)
class PairedObservation:
    timestamp: str
    session: str
    actual_up: int
    incumbent_p: float
    challenger_p: float
    symbol: str = ""

def _finite_probability_pct(value: Any) -> float | None:
    try: p = float(value) / 100.0
    except (TypeError, ValueError, OverflowError): return None
    if not np.isfinite(p) or p < 0.0 or p > 1.0: return None
    return float(np.clip(p, 1e-9, 1.0 - 1e-9))

def _session_key(timestamp: str) -> str | None:
    try: return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError): return None

def _normalize_records(records: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], Tuple[int, float]]:
    result = {}
    for row in records:
        if not isinstance(row, Mapping): continue
        timestamp = str(row.get("timestamp") or "").strip(); symbol = str(row.get("symbol") or "").upper().strip(); session = _session_key(timestamp); p = _finite_probability_pct(row.get("p_up"))
        try: actual = int(row.get("actual_up"))
        except (TypeError, ValueError): continue
        if not timestamp or session is None or p is None or actual not in (0, 1): continue
        key = (symbol, timestamp); candidate = (actual, p)
        if key in result and result[key] != candidate: raise ValueError(f"Conflicting duplicate record at {symbol + '@' if symbol else ''}{timestamp}")
        result[key] = candidate
    return result

def pair_records(incumbent_records, challenger_records):
    incumbent = _normalize_records(incumbent_records); challenger = _normalize_records(challenger_records); paired = []
    for symbol, timestamp in sorted(set(incumbent) & set(challenger), key=lambda key: (key[1], key[0])):
        ia, ip = incumbent[(symbol, timestamp)]; ca, cp = challenger[(symbol, timestamp)]
        if ia != ca: raise ValueError(f"Outcome mismatch at {symbol + '@' if symbol else ''}{timestamp}")
        paired.append(PairedObservation(timestamp, _session_key(timestamp) or "", ia, ip, cp, symbol))
    return paired

def _brier(y, p): return float(np.mean((p-y)**2))
def _log_loss(y, p): p=np.clip(p,1e-9,1-1e-9); return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def _directional_accuracy(y,p): return float(np.mean((p>=.5).astype(int)==y))
def _ece(y,p,bins=10):
    if not len(y): return float("nan")
    error=0.; edges=np.linspace(0,1,bins+1)
    for i in range(bins):
        low,high=edges[i],edges[i+1]; mask=(p>=low)&(p < high if i < bins-1 else p<=high)
        if mask.any(): error += float(mask.sum())/len(y)*abs(float(np.mean(y[mask]))-float(np.mean(p[mask])))
    return error

def _metrics(rows, field):
    y=np.asarray([r.actual_up for r in rows],float); p=np.asarray([getattr(r,field) for r in rows],float)
    return {"brier_score":round(_brier(y,p),6),"log_loss":round(_log_loss(y,p),6),"directional_accuracy":round(_directional_accuracy(y,p),6),"ece_10bin":round(_ece(y,p),6)}
def _session_deltas(rows):
    grouped=defaultdict(list)
    for r in rows: grouped[r.session].append(r)
    out={}
    for session, rs in grouped.items():
        y=np.asarray([r.actual_up for r in rs],float); i=np.asarray([r.incumbent_p for r in rs],float); c=np.asarray([r.challenger_p for r in rs],float); out[session]=(_brier(y,i)-_brier(y,c),_log_loss(y,i)-_log_loss(y,c))
    return out

def _bootstrap_session_ci(rows, *, samples=BOOTSTRAP_SAMPLES, seed=DEFAULT_SEED):
    d=_session_deltas(rows); sessions=sorted(d)
    if not sessions: return {"available":False,"reason":"no_sessions"}
    b=np.asarray([d[s][0] for s in sessions]); l=np.asarray([d[s][1] for s in sessions]); rng=np.random.default_rng(seed); bb=np.empty(samples); bl=np.empty(samples)
    for x in range(samples):
        idx=rng.integers(0,len(sessions),size=len(sessions)); bb[x]=np.mean(b[idx]); bl[x]=np.mean(l[idx])
    return {"available":True,"method":"paired_session_block_bootstrap","samples":samples,"seed":seed,"brier_improvement_ci95":[round(float(np.quantile(bb,.025)),6),round(float(np.quantile(bb,.975)),6)],"log_loss_improvement_ci95":[round(float(np.quantile(bl,.025)),6),round(float(np.quantile(bl,.975)),6)],"probability_brier_improvement_positive":round(float(np.mean(bb>0)),6),"probability_log_loss_improvement_positive":round(float(np.mean(bl>0)),6)}
def evaluate_paired_horizon(incumbent_records, challenger_records, *, min_observations=MIN_PAIRED_OBSERVATIONS, min_sessions=MIN_DISTINCT_SESSIONS, bootstrap_samples=BOOTSTRAP_SAMPLES, seed=DEFAULT_SEED):
    paired=pair_records(incumbent_records,challenger_records); sessions=sorted({r.session for r in paired}); incumbent=_metrics(paired,"incumbent_p") if paired else None; challenger=_metrics(paired,"challenger_p") if paired else None; coverage_ok=len(paired)>=min_observations and len(sessions)>=min_sessions; bootstrap=_bootstrap_session_ci(paired,samples=bootstrap_samples,seed=seed) if paired else {"available":False,"reason":"no_paired_records"}
    if incumbent and challenger: bi=round(incumbent["brier_score"]-challenger["brier_score"],6); li=round(incumbent["log_loss"]-challenger["log_loss"],6); ad=round(challenger["directional_accuracy"]-incumbent["directional_accuracy"],6); ei=round(incumbent["ece_10bin"]-challenger["ece_10bin"],6)
    else: bi=li=ad=ei=None
    stable=bool(coverage_ok and bootstrap.get("available") and bootstrap["brier_improvement_ci95"][0]>0 and bootstrap["log_loss_improvement_ci95"][0]>0); point=bool(bi is not None and li is not None and bi>0 and li>0)
    return {"paired_observations":len(paired),"distinct_sessions":len(sessions),"minimum_observations":min_observations,"minimum_sessions":min_sessions,"coverage_ok":coverage_ok,"incumbent":incumbent,"challenger":challenger,"brier_improvement":bi,"log_loss_improvement":li,"directional_accuracy_delta":ad,"ece_improvement":ei,"bootstrap":bootstrap,"verdict":"research_eligible" if stable and point else "not_demonstrated"}
def _validate_tournament_registration(registration, challenger_records, horizons):
    validated=validate_registration(registration); registered=set(validated["candidate"]["horizons"]); required=set(horizons)
    if not required.issubset(registered): raise ValueError("challenger registration does not cover tournament horizons: " + ", ".join(sorted(required-registered)))
    evidence=[]
    for horizon in horizons:
        rows=challenger_records.get(horizon) or []
        if not isinstance(rows,list): raise ValueError(f"challenger prediction_records.{horizon} must be a list")
        evidence.extend({**row,"horizon":horizon} for row in rows if isinstance(row,Mapping))
    eligibility=assert_forward_evidence_eligible(validated,evidence)
    if not eligibility["forward_evidence_eligible"]: raise ValueError(f"challenger evidence violates immutable preregistration: {eligibility}")
    return {"candidate_id":validated["candidate_id"],"immutable_material_sha256":validated["immutable_material_sha256"],"forward_cutoff_utc":eligibility["forward_cutoff_utc"],"observations_checked":eligibility["observations"],"forward_evidence_eligible":True}
def compare_reports(incumbent, challenger, *, registration, horizons=HORIZONS, min_observations=MIN_PAIRED_OBSERVATIONS, min_sessions=MIN_DISTINCT_SESSIONS, bootstrap_samples=BOOTSTRAP_SAMPLES, seed=DEFAULT_SEED):
    ir=incumbent.get("prediction_records") or {}; cr=challenger.get("prediction_records") or {}
    if not isinstance(ir,Mapping) or not isinstance(cr,Mapping): raise ValueError("Both reports must contain prediction_records mappings")
    gate=_validate_tournament_registration(registration,cr,horizons); results={}; eligible=0
    for offset,horizon in enumerate(horizons):
        result=evaluate_paired_horizon(ir.get(horizon) or [],cr.get(horizon) or [],min_observations=min_observations,min_sessions=min_sessions,bootstrap_samples=bootstrap_samples,seed=seed+offset); results[horizon]=result; eligible += int(result["verdict"]=="research_eligible")
    return {"contract":"orion-intraday-challenger-tournament-v2","semantics":SEMANTICS,"paired_only":True,"runtime_modified":False,"preregistration_required":True,"registration_gate":gate,"horizons_required":list(horizons),"eligible_horizons":eligible,"research_conclusion":"challenger_research_eligible" if eligible==len(horizons) else "challenger_not_demonstrated","horizons":results}
def main():
    parser=argparse.ArgumentParser(description="Leakage-safe paired tournament for Orion intraday challenger reports."); parser.add_argument("incumbent_report"); parser.add_argument("challenger_report"); parser.add_argument("--registration",required=True); parser.add_argument("--output"); parser.add_argument("--min-observations",type=int,default=MIN_PAIRED_OBSERVATIONS); parser.add_argument("--min-sessions",type=int,default=MIN_DISTINCT_SESSIONS); parser.add_argument("--bootstrap-samples",type=int,default=BOOTSTRAP_SAMPLES); args=parser.parse_args()
    with open(args.incumbent_report,encoding="utf-8") as h: incumbent=json.load(h)
    with open(args.challenger_report,encoding="utf-8") as h: challenger=json.load(h)
    with open(args.registration,encoding="utf-8") as h: registration=json.load(h)
    result=compare_reports(incumbent,challenger,registration=registration,min_observations=args.min_observations,min_sessions=args.min_sessions,bootstrap_samples=args.bootstrap_samples); payload=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:
        with open(args.output,"w",encoding="utf-8") as h: h.write(payload+"\n")
    else: print(payload)
    return 0
if __name__ == "__main__": raise SystemExit(main())
