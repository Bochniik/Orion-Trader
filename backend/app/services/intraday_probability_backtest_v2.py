
from __future__ import annotations
from math import isfinite
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import (
    HORIZONS,
    HORIZON_MINUTES,
    NEW_YORK,
    _normalize_ohlcv,
)
from app.services.intraday_probability_statistical_engine import (
    FEATURES,
    attach_targets,
    build_statistical_features,
    fit_horizon_model,
)

SEMANTICS = (
    "Chronological walk-forward validation for OrionTrader Probability V2. "
    "Every forecast uses only prior resolved outcomes."
)

def _brier(y,p):
    return float(np.mean((p-y)**2)) if len(y) else float("nan")

def _logloss(y,p):
    if not len(y): return float("nan")
    p=np.clip(p,1e-9,1-1e-9)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))

def _bins(records):
    result=[]
    for low in range(0,100,10):
        high=low+10
        rows=[r for r in records if low<=r["p_up"]<high or (high==100 and r["p_up"]==100)]
        if not rows: continue
        pred=np.mean([r["p_up"] for r in rows])
        actual=np.mean([r["actual_up"] for r in rows])*100
        result.append({
            "range":f"{low}-{high}",
            "count":len(rows),
            "average_predicted_up_pct":round(float(pred),2),
            "actual_up_rate_pct":round(float(actual),2),
            "calibration_gap_pct":round(float(actual-pred),2),
        })
    return result

def _ece(bins):
    total=sum(x["count"] for x in bins)
    if not total: return None
    return round(sum((x["count"]/total)*abs(x["calibration_gap_pct"]) for x in bins),3)

def _summary(records):
    if not records:
        return {"available":False,"prediction_count":0}
    y=np.array([r["actual_up"] for r in records],float)
    p=np.array([r["p_up"]/100 for r in records],float)

    directional=(p>=.55)|(p<=.45)
    if directional.any():
        pred=(p[directional]>=.5).astype(float)
        dacc=float(np.mean(pred==y[directional]))
    else:
        dacc=float("nan")

    def confident(th):
        mask=(p>=th)|(p<=1-th)
        if not mask.any():
            return {"count":0,"accuracy_pct":None}
        pred=(p[mask]>=.5).astype(float)
        return {"count":int(mask.sum()),"accuracy_pct":round(float(np.mean(pred==y[mask]))*100,2)}

    bins=_bins(records)
    return {
        "available":True,
        "prediction_count":len(records),
        "actual_up_rate_pct":round(float(np.mean(y))*100,2),
        "average_predicted_up_pct":round(float(np.mean(p))*100,2),
        "accuracy_at_50_pct":round(float(np.mean((p>=.5).astype(float)==y))*100,2),
        "directional_prediction_count":int(directional.sum()),
        "directional_accuracy_pct":round(dacc*100,2) if isfinite(dacc) else None,
        "confident_60":confident(.60),
        "confident_65":confident(.65),
        "brier_score":round(_brier(y,p),5),
        "log_loss":round(_logloss(y,p),5),
        "expected_calibration_error_pct":_ece(bins),
        "calibration_bins":bins,
    }

def walk_forward_v2_frame(
    stock: pd.DataFrame,
    spy: pd.DataFrame,
    *,
    symbol="TEST",
    initial_training_days=15,
    stride_bars=6,
    max_predictions_per_horizon=None,
):
    stock=_normalize_ohlcv(stock)
    spy=_normalize_ohlcv(spy)
    dataset=attach_targets(build_statistical_features(stock,spy))

    local=dataset.index.tz_convert(NEW_YORK)
    dates=pd.Series(local.date,index=dataset.index)
    unique=list(dict.fromkeys(dates.tolist()))
    if len(unique)<=initial_training_days:
        return {"symbol":symbol,"available":False,"warnings":["Insufficient history."],"semantics":SEMANTICS}

    first=unique[initial_training_days]
    eligible=dataset.loc[dates>=first].dropna(subset=FEATURES)
    timestamps=list(eligible.index[::max(1,int(stride_bars))])

    records={h:[] for h in HORIZONS}
    skipped={h:0 for h in HORIZONS}

    for ts in timestamps:
        row=dataset.loc[ts]
        if isinstance(row,pd.DataFrame):
            row=row.iloc[-1]

        for h in HORIZONS:
            if max_predictions_per_horizon and len(records[h])>=max_predictions_per_horizon:
                continue

            actual=row.get(f"target_up_{h}")
            if pd.isna(actual):
                skipped[h]+=1
                continue

            result=fit_horizon_model(dataset.loc[:ts].copy(),ts,h)
            if not result.get("available"):
                skipped[h]+=1
                continue

            records[h].append({
                "timestamp":pd.Timestamp(ts).isoformat(),
                "p_up":float(result["probability_up"]),
                "actual_up":int(actual),
            })

    return {
        "symbol":symbol.upper(),
        "available":any(records[h] for h in HORIZONS),
        "method":"chronological_walk_forward_horizon_specific_logistic_v2",
        "bar_count":len(stock),
        "test_timestamp_count":len(timestamps),
        "initial_training_days":initial_training_days,
        "stride_bars":stride_bars,
        "horizons":{h:_summary(records[h]) for h in HORIZONS},
        "skipped_predictions":skipped,
        "semantics":SEMANTICS,
    }

def walk_forward_v2(symbol,period="60d",interval="5m"):
    import yfinance as yf
    ticker=symbol.strip().upper()
    stock=yf.download(ticker,period=period,interval=interval,auto_adjust=False,prepost=False,progress=False,threads=False)
    spy=yf.download("SPY",period=period,interval=interval,auto_adjust=False,prepost=False,progress=False,threads=False)
    result=walk_forward_v2_frame(stock,spy,symbol=ticker)
    result["period"]=period
    result["interval"]=interval
    return result

if __name__=="__main__":
    import json,sys
    ticker=sys.argv[1].upper() if len(sys.argv)>1 else "NVDA"
    print(json.dumps(walk_forward_v2(ticker),indent=2,ensure_ascii=False,default=str))
