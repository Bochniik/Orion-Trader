from __future__ import annotations
import math
import numpy as np
import pandas as pd

from app.services.intraday_probability_engine import NEW_YORK, _normalize_ohlcv
from app.services.intraday_probability_statistical_engine import (
    FEATURES, L2, MIN_TRAIN, attach_targets, build_statistical_features,
    _fit_logistic, _predict,
)

MODEL_NAME = "orion_v5_30m_specialist"
TARGET = "target_up_30m"
EXTRA = [
    "ret_1","ret_3","ret_6","ret_12","mom_accel_3_6","vol_ratio_3_12",
    "range_pos_12","range_pos_24","vwap_dist","vwap_slope_6",
    "volatility_6","volatility_12","spy_rel_3","spy_rel_6",
    "trend_x_vwap","momentum_x_volume","trend_x_market","volatility_x_momentum",
    "tod_sin","tod_cos",
]
ALL_FEATURES = FEATURES + EXTRA
L2_MULTIPLIERS = (0.5, 1.0, 2.0, 4.0)
SHRINK_GRID = (0.25, 0.40, 0.55, 0.70, 0.85, 1.0)
BLEND_GRID = (0.25, 0.50, 0.75)
CONF_GRID = (0.53, 0.55, 0.57, 0.60)
BOOST_ROUNDS = 16
BOOST_LR = 0.22


def _canonicalize(frame):
    out = pd.DataFrame(index=frame.index)
    for wanted in ("Open","High","Low","Close","Volume"):
        wl = wanted.lower(); found = None
        for col in frame.columns:
            parts = [str(x).strip().lower() for x in col if str(x).strip()] if isinstance(col, tuple) else [str(col).strip().lower()]
            if wl in parts:
                found = col; break
        if found is None:
            raise KeyError(f"{wanted} missing; columns={list(frame.columns)!r}")
        s = frame[found]
        if isinstance(s, pd.DataFrame): s = s.iloc[:,0]
        out[wanted] = pd.to_numeric(s, errors="coerce")
    return out.sort_index()


def _add_features(stock, spy, dataset):
    f = dataset.copy(); stock = stock.reindex(f.index); spy = spy.reindex(f.index).ffill()
    c = stock["Close"].astype(float); v = stock["Volume"].astype(float)
    h = stock["High"].astype(float); l = stock["Low"].astype(float); sc = spy["Close"].astype(float)
    for n in (1,3,6,12): f[f"ret_{n}"] = c.pct_change(n)
    f["mom_accel_3_6"] = f["ret_3"] - f["ret_6"] / 2.0
    f["vol_ratio_3_12"] = v.rolling(3,min_periods=2).mean() / v.rolling(12,min_periods=6).mean().replace(0,np.nan)
    for w in (12,24):
        lo=l.rolling(w,min_periods=max(4,w//3)).min(); hi=h.rolling(w,min_periods=max(4,w//3)).max()
        f[f"range_pos_{w}"]=(c-lo)/(hi-lo).replace(0,np.nan)
    day = pd.Series(f.index.tz_convert(NEW_YORK).date,index=f.index)
    typical=(h+l+c)/3.0; pv=typical*v; vwap=pd.Series(index=f.index,dtype=float)
    for d in dict.fromkeys(day.tolist()):
        m=day==d; cv=v.loc[m].cumsum().replace(0,np.nan); vwap.loc[m]=pv.loc[m].cumsum()/cv
    f["vwap_dist"]=c/vwap-1.0; f["vwap_slope_6"]=vwap.pct_change(6)
    r1=c.pct_change(); f["volatility_6"]=r1.rolling(6,min_periods=4).std(); f["volatility_12"]=r1.rolling(12,min_periods=6).std()
    f["spy_rel_3"]=f["ret_3"]-sc.pct_change(3); f["spy_rel_6"]=f["ret_6"]-sc.pct_change(6)
    f["trend_x_vwap"]=f["ret_6"]*f["vwap_dist"]
    f["momentum_x_volume"]=f["ret_3"]*(f["vol_ratio_3_12"]-1.0)
    f["trend_x_market"]=f["ret_6"]*f["spy_rel_6"]
    f["volatility_x_momentum"]=f["volatility_6"]*f["ret_3"]
    local=f.index.tz_convert(NEW_YORK); minute=local.hour*60+local.minute; phase=2*np.pi*((minute-570)/390.0)
    f["tod_sin"]=np.sin(phase); f["tod_cos"]=np.cos(phase)
    return f


def _scale_fit(frame):
    X=frame[ALL_FEATURES].astype(float).to_numpy(); med=np.nanmedian(X,axis=0)
    q1=np.nanquantile(X,.25,axis=0); q3=np.nanquantile(X,.75,axis=0); scale=q3-q1; std=np.nanstd(X,axis=0)
    scale=np.where(np.isfinite(scale)&(scale>1e-10),scale,np.where(np.isfinite(std)&(std>1e-10),std,1.0))
    X=np.nan_to_num(np.clip((X-med)/scale,-8,8),nan=0.0,posinf=8.0,neginf=-8.0)
    return X,med,scale


def _scale_apply(frame,med,scale):
    X=frame[ALL_FEATURES].astype(float).to_numpy()
    return np.nan_to_num(np.clip((X-med)/scale,-8,8),nan=0.0,posinf=8.0,neginf=-8.0)


def _sigmoid(x): return 1/(1+np.exp(-np.clip(x,-35,35)))


def _fit_stumps(X,y):
    base=float(np.clip(np.mean(y),.03,.97)); bias=math.log(base/(1-base)); logits=np.full(len(y),bias); stumps=[]
    qs=np.quantile(X,(.2,.4,.6,.8),axis=0)
    for _ in range(BOOST_ROUNDS):
        p=_sigmoid(logits); r=y-p; best=None
        for j in range(X.shape[1]):
            for t in np.unique(qs[:,j]):
                left=X[:,j]<=t; right=~left
                if left.sum()<30 or right.sum()<30: continue
                wl=(p[left]*(1-p[left])).sum()+6.0; wr=(p[right]*(1-p[right])).sum()+6.0
                sl=r[left].sum(); sr=r[right].sum(); lv=sl/wl; rv=sr/wr; gain=sl*sl/wl+sr*sr/wr
                if best is None or gain>best[0]: best=(gain,j,float(t),float(lv),float(rv))
        if best is None: break
        _,j,t,lv,rv=best; logits += BOOST_LR*np.where(X[:,j]<=t,lv,rv); stumps.append((j,t,lv,rv))
    return {"bias":bias,"stumps":stumps}


def _predict_stumps(model,X):
    logits=np.full(len(X),model["bias"])
    for j,t,lv,rv in model["stumps"]: logits += BOOST_LR*np.where(X[:,j]<=t,lv,rv)
    return _sigmoid(logits)


def _brier(y,p): return float(np.mean((p-y)**2))
def _logloss(y,p):
    p=np.clip(p,1e-9,1-1e-9); return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))

def _wilson(correct,n,z=1.96):
    if n<=0:return None
    ph=correct/n; den=1+z*z/n; center=ph+z*z/(2*n); adj=z*math.sqrt((ph*(1-ph)+z*z/(4*n))/n)
    return (center-adj)/den


def _choose_threshold(y,p):
    best=None
    for th in CONF_GRID:
        m=(p>=th)|(p<=1-th); n=int(m.sum())
        if n<60 or n/len(y)<.12: continue
        pred=(p[m]>=.5).astype(float); c=int(np.sum(pred==y[m])); score=(_wilson(c,n) or 0,c/n,n)
        if best is None or score>best[0]: best=(score,th)
    return best[1] if best else .55


def _select_model(train):
    split=max(450,int(len(train)*.72)); split=min(split,len(train)-80)
    if split<300:return None
    fit=train.iloc[:split]; val=train.iloc[split:]
    Xf,med,scale=_scale_fit(fit); Xv=_scale_apply(val,med,scale); yf=fit[TARGET].to_numpy(float); yv=val[TARGET].to_numpy(float)
    stump=_fit_stumps(Xf,yf); sp=_predict_stumps(stump,Xv); best=None; base=float(L2["30m"])
    for mult in L2_MULTIPLIERS:
        w=_fit_logistic(Xf,yf,l2=base*mult); lp=np.asarray(_predict(w,Xv),dtype=float)
        for a in BLEND_GRID:
            raw=a*lp+(1-a)*sp
            for shrink in SHRINK_GRID:
                p=np.clip(.5+(raw-.5)*shrink,.03,.97); loss=_brier(yv,p)+.25*_logloss(yv,p)
                if best is None or loss<best[0]: best=(loss,base*mult,a,shrink)
    if best is None:return None
    _,l2v,a,shrink=best; w=_fit_logistic(Xf,yf,l2=l2v); lp=np.asarray(_predict(w,Xv),dtype=float)
    p=np.clip(.5+(a*lp+(1-a)*sp-.5)*shrink,.03,.97); threshold=_choose_threshold(yv,p)
    X,med,scale=_scale_fit(train); y=train[TARGET].to_numpy(float)
    return {"med":med,"scale":scale,"weights":_fit_logistic(X,y,l2=l2v),"stump":_fit_stumps(X,y),"alpha":a,"shrink":shrink,"threshold":threshold}


def _predict_model(model,row):
    X=_scale_apply(pd.DataFrame([row]),model["med"],model["scale"]); lp=float(_predict(model["weights"],X)[0]); sp=float(_predict_stumps(model["stump"],X)[0])
    return float(np.clip(.5+(model["alpha"]*lp+(1-model["alpha"])*sp-.5)*model["shrink"],.03,.97))


def _ece(y,p):
    e=0.0
    for lo in np.arange(0,1,.1):
        hi=lo+.1; m=(p>=lo)&(p<(hi if hi<1 else 1.0001))
        if m.any(): e += m.sum()/len(y)*abs(float(np.mean(p[m])-np.mean(y[m])))
    return e


def _summary(records):
    if not records:return {"available":False,"prediction_count":0}
    y=np.array([r["y"] for r in records],float); p=np.array([r["p"] for r in records],float); pred=(p>=.5).astype(float)
    sel=np.array([r["selected"] for r in records],bool); sn=int(sel.sum()); sa=slb=None
    if sn:
        spr=(p[sel]>=.5).astype(float); c=int(np.sum(spr==y[sel])); sa=c/sn; slb=_wilson(c,sn)
    c60=(p>=.60)|(p<=.40); c60a=float(np.mean((p[c60]>=.5).astype(float)==y[c60])) if c60.any() else None
    return {
        "available":True,"prediction_count":len(y),"accuracy_at_50_pct":round(float(np.mean(pred==y))*100,2),
        "brier_score":round(_brier(y,p),5),"log_loss":round(_logloss(y,p),5),"ece_pct":round(_ece(y,p)*100,3),
        "selected_prediction_count":sn,"selected_coverage_pct":round(sn/len(y)*100,2),
        "selected_accuracy_pct":None if sa is None else round(sa*100,2),"selected_wilson_lower_95_pct":None if slb is None else round(slb*100,2),
        "confident_60_count":int(c60.sum()),"confident_60_accuracy_pct":None if c60a is None else round(c60a*100,2),
        "distinct_trading_days":len(set(r["day"] for r in records)),
    }


def walk_forward_v5_30m_frame(stock,spy,*,symbol="TEST",initial_training_days=15,stride_bars=6):
    stock=_canonicalize(_normalize_ohlcv(stock)); spy=_canonicalize(_normalize_ohlcv(spy))
    ds=attach_targets(build_statistical_features(stock,spy)); ds=_add_features(stock,spy,ds)
    local=ds.index.tz_convert(NEW_YORK); dates=pd.Series(local.date,index=ds.index); unique=list(dict.fromkeys(dates.tolist()))
    records=[]; skipped=0; refits=0
    for day in unique[initial_training_days:]:
        rows=ds.loc[dates==day].dropna(subset=ALL_FEATURES); test=rows.iloc[::max(1,int(stride_bars))]
        if test.empty:continue
        cutoff=test.index[0]-pd.Timedelta(minutes=30); train=ds.loc[ds.index<=cutoff].dropna(subset=ALL_FEATURES+[TARGET]).copy()
        if len(train)<MIN_TRAIN["30m"]: skipped+=len(test); continue
        model=_select_model(train)
        if model is None: skipped+=len(test); continue
        refits+=1; th=float(model["threshold"])
        for ts,row in test.iterrows():
            y=row.get(TARGET)
            if pd.isna(y): skipped+=1; continue
            p=_predict_model(model,row); records.append({"day":str(day),"p":p,"y":int(y),"selected":(p>=th or p<=1-th)})
    return {"symbol":symbol.upper(),"available":bool(records),"method":MODEL_NAME,"horizon":"30m","feature_count":len(ALL_FEATURES),"daily_model_refits":refits,"skipped_predictions":skipped,"metrics":_summary(records),"production_modified":False,
            "semantics":"30m-only leakage-safe daily-refit specialist blending regularized logistic regression and shallow boosted decision stumps. Hyperparameters and NO_TRADE threshold are selected only on chronological inner-validation data available before each test day."}


def walk_forward_v5_30m(symbol,period="60d",interval="5m"):
    import yfinance as yf
    ticker=symbol.strip().upper(); stock=yf.download(ticker,period=period,interval=interval,auto_adjust=False,prepost=False,progress=False,threads=False); spy=yf.download("SPY",period=period,interval=interval,auto_adjust=False,prepost=False,progress=False,threads=False)
    r=walk_forward_v5_30m_frame(stock,spy,symbol=ticker); r["period"]=period; r["interval"]=interval; return r

if __name__=="__main__":
    import json,sys
    print(json.dumps(walk_forward_v5_30m(sys.argv[1] if len(sys.argv)>1 else "AAPL"),indent=2,default=str))
