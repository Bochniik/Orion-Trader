
from __future__ import annotations
from math import isfinite
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import (
    HORIZONS,
    HORIZON_MINUTES,
    NEW_YORK,
    _normalize_ohlcv,
    _session_key,
)

FEATURES = [
    "ret_5m","ret_15m","ret_30m","ret_60m","volatility_30m","volume_z",
    "vwap_distance","range_position","trend_slope","rsi_14","macd_hist",
    "atr_pct","vwap_slope_30m","return_from_open","distance_from_session_high",
    "distance_from_session_low","time_fraction","spy_ret_5m","spy_ret_30m",
    "spy_ret_60m","relative_strength_30m","relative_strength_60m",
]

MIN_TRAIN = {"30m":450,"1h":420,"3h":300,"5h":180}
L2 = {"30m":2.0,"1h":2.5,"3h":3.5,"5h":5.0}

SEMANTICS = (
    "Horizon-specific statistical estimate of P(up)/P(down) using only "
    "historically resolved regular-session observations. Separate from Orion Score."
)

def _sigmoid(x):
    x = np.clip(x, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-x))

def _fit_logistic(X, y, l2=2.0, iterations=450, lr=0.08):
    n, p = X.shape
    Xb = np.column_stack([np.ones(n), X])
    w = np.zeros(p + 1)
    for step in range(iterations):
        pred = _sigmoid(Xb @ w)
        grad = (Xb.T @ (pred - y)) / n
        grad += np.r_[0.0, l2 * w[1:] / n]
        w -= (lr / (1.0 + 0.0025 * step)) * grad
    return w

def _predict(w, X):
    Xb = np.column_stack([np.ones(len(X)), X])
    return _sigmoid(Xb @ w)

def _ema(s, span):
    return s.ewm(span=span, adjust=False, min_periods=max(3, span//3)).mean()

def _rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0.0)
    l = -d.clip(upper=0.0)
    ag = g.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    al = l.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _atr(frame, period=14):
    pc = frame["Close"].shift(1)
    tr = pd.concat([
        frame["High"] - frame["Low"],
        (frame["High"] - pc).abs(),
        (frame["Low"] - pc).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

def build_statistical_features(stock: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    f = stock.copy()
    c = f["Close"].astype(float)
    v = f["Volume"].astype(float)
    session = _session_key(f.index)

    f["ret_5m"] = c.pct_change(1)
    f["ret_15m"] = c.pct_change(3)
    f["ret_30m"] = c.pct_change(6)
    f["ret_60m"] = c.pct_change(12)
    f["volatility_30m"] = c.pct_change().rolling(6, min_periods=4).std()

    vm = v.rolling(20, min_periods=8).mean()
    vs = v.rolling(20, min_periods=8).std().replace(0,np.nan)
    f["volume_z"] = (v-vm)/vs

    typical = (f["High"]+f["Low"]+f["Close"])/3.0
    cum_pv = (typical*v).groupby(session.values).cumsum()
    cum_v = v.groupby(session.values).cumsum().replace(0,np.nan)
    f["session_vwap"] = cum_pv/cum_v
    f["vwap_distance"] = c/f["session_vwap"]-1.0
    f["vwap_slope_30m"] = f["session_vwap"].pct_change(6)

    rh = f["High"].rolling(12,min_periods=4).max()
    rl = f["Low"].rolling(12,min_periods=4).min()
    f["range_position"] = (c-rl)/(rh-rl).replace(0,np.nan)
    f["trend_slope"] = np.log(c.replace(0,np.nan)).diff(6)/6.0

    f["rsi_14"] = _rsi(c)/100.0
    macd = _ema(c,12)-_ema(c,26)
    f["macd_hist"] = (macd-_ema(macd,9))/c.replace(0,np.nan)
    f["atr_pct"] = _atr(f)/c.replace(0,np.nan)

    sess_open = f["Open"].groupby(session.values).transform("first")
    sess_high = f["High"].groupby(session.values).cummax()
    sess_low = f["Low"].groupby(session.values).cummin()
    f["return_from_open"] = c/sess_open.replace(0,np.nan)-1.0
    f["distance_from_session_high"] = c/sess_high.replace(0,np.nan)-1.0
    f["distance_from_session_low"] = c/sess_low.replace(0,np.nan)-1.0

    local = f.index.tz_convert(NEW_YORK)
    mins = local.hour*60 + local.minute
    f["time_fraction"] = (mins-(9*60+30))/390.0

    spy_aligned = spy.reindex(f.index).ffill()
    sc = spy_aligned["Close"].astype(float)
    f["spy_ret_5m"] = sc.pct_change(1)
    f["spy_ret_30m"] = sc.pct_change(6)
    f["spy_ret_60m"] = sc.pct_change(12)
    f["relative_strength_30m"] = f["ret_30m"]-f["spy_ret_30m"]
    f["relative_strength_60m"] = f["ret_60m"]-f["spy_ret_60m"]
    return f

def attach_targets(frame):
    r = frame.copy()
    session = _session_key(r.index)
    for label,bars in HORIZONS.items():
        fc = r["Close"].shift(-bars)
        fs = session.shift(-bars)
        ret = (fc/r["Close"]-1.0).where(session.eq(fs))
        r[f"target_return_{label}"] = ret
        r[f"target_up_{label}"] = (ret>0).astype(float).where(ret.notna())
    return r

def _scale_fit(frame):
    X = frame[FEATURES].astype(float).to_numpy()
    med = np.nanmedian(X,axis=0)
    q1 = np.nanquantile(X,.25,axis=0)
    q3 = np.nanquantile(X,.75,axis=0)
    scale = q3-q1
    std = np.nanstd(X,axis=0)
    scale = np.where(np.isfinite(scale)&(scale>1e-10),scale,
                     np.where(np.isfinite(std)&(std>1e-10),std,1.0))
    return np.clip((X-med)/scale,-8,8), med, scale

def _scale_one(row, med, scale):
    x = row[FEATURES].astype(float).to_numpy()
    return np.clip((x-med)/scale,-8,8)

def _local_calibrate(raw_p, probs, y):
    if len(probs) < 80:
        return raw_p, {"available":False,"sample_size":len(probs)}
    dist = np.abs(probs-raw_p)
    idx = np.argsort(dist)[:min(80,len(dist))]
    lp, ly = probs[idx], y[idx]
    observed = float(np.mean(ly))
    mean_pred = float(np.mean(lp))
    shrink = len(idx)/(len(idx)+60.0)
    correction = (observed-mean_pred)*shrink
    calibrated = float(np.clip(raw_p+correction,.02,.98))
    return calibrated, {
        "available":True,
        "sample_size":len(idx),
        "local_observed_up_rate_pct":round(observed*100,2),
        "local_mean_raw_probability_pct":round(mean_pred*100,2),
        "correction_pct_points":round(correction*100,2),
        "method":"local_reliability_correction"
    }

def fit_horizon_model(dataset, current_timestamp, horizon):
    target = f"target_up_{horizon}"
    cutoff = current_timestamp-pd.Timedelta(minutes=HORIZON_MINUTES[horizon])
    train = dataset.loc[dataset.index<=cutoff].dropna(subset=FEATURES+[target]).copy()

    if len(train) < MIN_TRAIN[horizon]:
        return {"available":False,"training_samples":len(train),
                "reason":f"Need at least {MIN_TRAIN[horizon]} resolved rows."}

    current = dataset.loc[current_timestamp]
    if isinstance(current,pd.DataFrame):
        current=current.iloc[-1]
    if current[FEATURES].isna().any():
        return {"available":False,"reason":"Current feature vector incomplete."}

    split=max(MIN_TRAIN[horizon]//2,int(len(train)*.80))
    fit=train.iloc[:split]
    cal=train.iloc[split:]
    if len(cal)<40:
        fit=train
        cal=train.iloc[0:0]

    X,med,scale=_scale_fit(fit)
    y=fit[target].to_numpy(float)
    w=_fit_logistic(X,y,l2=L2[horizon])
    raw=float(_predict(w,_scale_one(current,med,scale).reshape(1,-1))[0])

    if len(cal):
        Xc=np.vstack([_scale_one(row,med,scale) for _,row in cal.iterrows()])
        cp=_predict(w,Xc)
        cy=cal[target].to_numpy(float)
        p,cal_info=_local_calibrate(raw,cp,cy)
    else:
        p,cal_info=raw,{"available":False,"sample_size":0}

    reliability=min(1.0,len(train)/1200.0)
    p=0.5+(p-0.5)*reliability
    p=float(np.clip(p,.03,.97))
    up=round(p*100,1)
    down=round(100-up,1)
    direction="bullish" if up>=55 else "bearish" if up<=45 else "neutral"

    return {
        "available":True,
        "horizon":horizon,
        "direction":direction,
        "probability_up":up,
        "probability_down":down,
        "directional_confidence":round(abs(up-50)*2,1),
        "raw_model_probability_up":round(raw*100,2),
        "training_samples":len(train),
        "calibration":cal_info,
        "model":"horizon_specific_l2_logistic_regression",
        "feature_count":len(FEATURES),
    }

def _download(symbol,period="60d",interval="5m"):
    import yfinance as yf
    stock=yf.download(symbol,period=period,interval=interval,auto_adjust=False,
                      prepost=False,progress=False,threads=False)
    spy=yf.download("SPY",period=period,interval=interval,auto_adjust=False,
                    prepost=False,progress=False,threads=False)
    return _normalize_ohlcv(stock),_normalize_ohlcv(spy)

def estimate_intraday_probabilities_v2(symbol,period="60d",interval="5m"):
    ticker=str(symbol or "").strip().upper()
    if not ticker:
        raise ValueError("symbol is required")
    try:
        stock,spy=_download(ticker,period,interval)
    except Exception as exc:
        return {"symbol":ticker,"available":False,"horizons":{},
                "warnings":[f"Historical data request failed: {type(exc).__name__}"],
                "semantics":SEMANTICS}
    if len(stock)<500 or len(spy)<500:
        return {"symbol":ticker,"available":False,"horizons":{},
                "warnings":["Insufficient stock/SPY 5-minute history."],
                "semantics":SEMANTICS}

    dataset=attach_targets(build_statistical_features(stock,spy))
    current_rows=dataset.dropna(subset=FEATURES)
    if current_rows.empty:
        return {"symbol":ticker,"available":False,"horizons":{},
                "warnings":["Current feature vector incomplete."],"semantics":SEMANTICS}

    ts=current_rows.index[-1]
    local=pd.Timestamp(ts).tz_convert(NEW_YORK)
    remaining=max(0,16*60-(local.hour*60+local.minute))

    results={}
    for h in HORIZONS:
        need=HORIZON_MINUTES[h]
        if remaining<need:
            results[h]={"available":False,"horizon":h,"probability_up":None,
                        "probability_down":None,
                        "reason":f"Only {remaining} regular-session minutes remain; {need} required.",
                        "current_session_feasible":False}
        else:
            r=fit_horizon_model(dataset,ts,h)
            r["current_session_feasible"]=True
            results[h]=r

    av=[x for x in results.values() if x.get("available")]
    bull=sum(x.get("direction")=="bullish" for x in av)
    bear=sum(x.get("direction")=="bearish" for x in av)
    consensus="bullish" if bull>bear else "bearish" if bear>bull else "mixed_or_neutral"

    return {
        "symbol":ticker,
        "available":bool(av),
        "as_of":pd.Timestamp(ts).isoformat(),
        "bar_interval":interval,
        "history_period":period,
        "regular_session_minutes_remaining":remaining,
        "horizons":results,
        "cross_horizon_consensus":consensus,
        "warnings":[],
        "limitations":[
            "This is a statistical baseline, not a guarantee.",
            "Sector ETF and news/catalyst are not yet in the statistical feature vector.",
            "Keep walk-forward validation enabled before trusting high probabilities."
        ],
        "semantics":SEMANTICS
    }

def _synthetic_self_test():
    rng=np.random.default_rng(7)
    sessions=[]
    days=pd.bdate_range("2026-03-02",periods=50)
    price=100.0
    for i,day in enumerate(days):
        idx=pd.date_range(pd.Timestamp(day.date(),tz=NEW_YORK)+pd.Timedelta(hours=9,minutes=30),
                          periods=78,freq="5min")
        drift=.00025 if i%4 in (0,1) else -.00015
        noise=rng.normal(0,.0013,len(idx))
        rets=drift+.25*np.r_[0,noise[:-1]]+noise
        close=price*np.cumprod(1+rets)
        op=np.r_[price,close[:-1]]
        wick=np.abs(rng.normal(.0008,.0003,len(idx)))
        high=np.maximum(op,close)*(1+wick)
        low=np.minimum(op,close)*(1-wick)
        vol=rng.integers(300000,1800000,len(idx))
        sessions.append(pd.DataFrame({"Open":op,"High":high,"Low":low,"Close":close,"Volume":vol},index=idx))
        price=float(close[-1])
    stock=pd.concat(sessions)
    spy=stock.copy()
    spy["Close"]=100*np.cumprod(1+rng.normal(.00005,.0006,len(spy)))
    spy["Open"]=spy["Close"].shift(1).fillna(spy["Close"])
    spy["High"]=np.maximum(spy["Open"],spy["Close"])*1.0005
    spy["Low"]=np.minimum(spy["Open"],spy["Close"])*0.9995
    dataset=attach_targets(build_statistical_features(stock,spy))
    ts=dataset.dropna(subset=FEATURES).index[-70]
    return {"self_test":True,"as_of":pd.Timestamp(ts).isoformat(),
            "horizons":{h:fit_horizon_model(dataset,ts,h) for h in HORIZONS},
            "semantics":SEMANTICS}

if __name__=="__main__":
    import json,sys
    output=_synthetic_self_test() if "--self-test" in sys.argv else estimate_intraday_probabilities_v2(sys.argv[1] if len(sys.argv)>1 else "NVDA")
    print(json.dumps(output,indent=2,ensure_ascii=False,default=str))
