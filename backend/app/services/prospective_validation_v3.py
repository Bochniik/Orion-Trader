from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from app.services.intraday_probability_engine import (
    HORIZONS,
    NEW_YORK,
    _normalize_ohlcv,
)
from app.services.intraday_probability_statistical_engine import (
    FEATURES,
    attach_targets,
    build_statistical_features,
)
from app.services.intraday_probability_backtest_v3 import (
    _train_daily_model,
    _predict_with_model,
)

BACKEND = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND / "data" / "learning_validation" / "prospective_v3"
DB_PATH = DATA_DIR / "prospective_v3.db"

MODEL_VERSION = "logistic_v3_conservative_frozen_20260908"
HORIZONS_TO_COLLECT = ("3h", "5h")

DEFAULT_UNIVERSE = (
    "AAPL","MSFT","NVDA","AMD","META","AMZN","GOOGL","TSLA","AVGO","NFLX",
    "PLTR","MU","QCOM","INTC","ARM","SMCI",
    "JPM","BAC","GS","MS",
    "XOM","CVX","COP",
    "LLY","UNH","JNJ","MRK",
    "COST","WMT","HD",
    "BA","CAT","GE",
    "SPY","QQQ","IWM",
)

MIN_PREDICTION_SPACING_MINUTES = 30


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _flat_name(col):
    if isinstance(col, tuple):
        parts = [str(x).strip().lower() for x in col if str(x).strip()]
        return parts
    return [str(col).strip().lower()]


def _find_column(frame, wanted):
    wanted = wanted.lower()
    # Exact/simple column first.
    for col in frame.columns:
        parts = _flat_name(col)
        if wanted in parts:
            return col
        if len(parts) == 1 and parts[0] == wanted:
            return col
    # Last-resort textual match for flattened yfinance MultiIndex labels.
    for col in frame.columns:
        text = " ".join(_flat_name(col))
        if wanted == text or text.startswith(wanted + " ") or text.endswith(" " + wanted):
            return col
    raise KeyError(wanted)


def _series_value(row, frame, wanted):
    # Try the row directly, including case-insensitive keys/MultiIndex labels.
    try:
        if wanted in row.index:
            return float(row[wanted])
    except Exception:
        pass

    for key in row.index:
        parts = _flat_name(key)
        if wanted.lower() in parts:
            value = row[key]
            if isinstance(value, pd.Series):
                value = value.iloc[0]
            return float(value)

    col = _find_column(frame, wanted)
    value = row[col]
    if isinstance(value, pd.Series):
        value = value.iloc[0]
    return float(value)


def _frame_value_at(frame, ts, wanted):
    col = _find_column(frame, wanted)
    row = frame.loc[ts]
    value = row[col]
    if isinstance(value, pd.Series):
        value = value.iloc[0]
    return float(value)


def _frame_extreme(frame, wanted, mode):
    col = _find_column(frame, wanted)
    series = frame[col]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.max() if mode == "max" else series.min())


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_version TEXT NOT NULL,
            ticker TEXT NOT NULL,
            horizon TEXT NOT NULL,
            prediction_timestamp TEXT NOT NULL,
            source_bar_timestamp TEXT NOT NULL,
            target_timestamp TEXT NOT NULL,
            source_price REAL NOT NULL,
            p_up REAL NOT NULL,
            predicted_direction TEXT NOT NULL,
            feature_snapshot_json TEXT,
            training_samples INTEGER,
            selected_l2 REAL,
            selected_shrink REAL,
            created_at TEXT NOT NULL,
            UNIQUE(model_version, ticker, horizon, source_bar_timestamp)
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            prediction_id INTEGER PRIMARY KEY,
            settled_at TEXT NOT NULL,
            target_price REAL NOT NULL,
            actual_return_pct REAL NOT NULL,
            actual_up INTEGER NOT NULL,
            correct INTEGER NOT NULL,
            brier REAL NOT NULL,
            log_loss REAL NOT NULL,
            mfe_pct REAL,
            mae_pct REAL,
            target_bar_timestamp TEXT,
            FOREIGN KEY(prediction_id) REFERENCES predictions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_predictions_due
            ON predictions(target_timestamp);

        CREATE INDEX IF NOT EXISTS idx_predictions_ticker_horizon
            ON predictions(ticker, horizon, source_bar_timestamp);
        """
    )
    return con


def download_history(ticker, period="60d", interval="5m"):
    data = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    return _normalize_ohlcv(data)


def build_current_dataset(stock, spy):
    return attach_targets(build_statistical_features(stock, spy))


def latest_usable_row(dataset):
    usable = dataset.dropna(subset=FEATURES)
    if usable.empty:
        return None, None
    ts = usable.index[-1]
    return ts, usable.iloc[-1]


def feature_snapshot(row):
    snap = {}
    for key in FEATURES:
        value = row.get(key)
        if pd.isna(value):
            snap[key] = None
        else:
            try:
                snap[key] = float(value)
            except Exception:
                snap[key] = str(value)
    return snap


def last_prediction_ts(con, ticker, horizon):
    row = con.execute(
        """
        SELECT source_bar_timestamp
        FROM predictions
        WHERE model_version=? AND ticker=? AND horizon=?
        ORDER BY source_bar_timestamp DESC
        LIMIT 1
        """,
        (MODEL_VERSION, ticker, horizon),
    ).fetchone()
    return pd.Timestamp(row["source_bar_timestamp"]) if row else None


def should_collect(con, ticker, horizon, source_ts):
    previous = last_prediction_ts(con, ticker, horizon)
    if previous is None:
        return True
    source_ts = pd.Timestamp(source_ts)
    if previous.tzinfo is None:
        previous = previous.tz_localize("UTC")
    if source_ts.tzinfo is None:
        source_ts = source_ts.tz_localize("UTC")
    return (source_ts - previous) >= pd.Timedelta(minutes=MIN_PREDICTION_SPACING_MINUTES)


def collect_ticker(con, ticker, spy):
    stock = download_history(ticker)
    if stock.empty or spy.empty:
        return {"ticker": ticker, "status": "no_history"}

    dataset = build_current_dataset(stock, spy)
    source_ts, row = latest_usable_row(dataset)
    if row is None:
        return {"ticker": ticker, "status": "no_usable_features"}

    local = pd.Timestamp(source_ts).tz_convert(NEW_YORK)
    if not (local.hour > 9 or (local.hour == 9 and local.minute >= 30)):
        return {"ticker": ticker, "status": "outside_regular_session"}
    if local.hour > 15 or (local.hour == 15 and local.minute > 59):
        return {"ticker": ticker, "status": "outside_regular_session"}

    # FIX: do not use Series.get(..., stock.loc[...]["close"]) because Python
    # evaluates the default argument eagerly. The old code therefore raised
    # KeyError('close') even when the feature row itself was valid.
    source_stock_row = stock.loc[source_ts]
    source_price = _series_value(source_stock_row, stock, "close")

    inserted = []
    for horizon in HORIZONS_TO_COLLECT:
        if horizon not in HORIZONS or not should_collect(con, ticker, horizon, source_ts):
            continue

        model = _train_daily_model(dataset, source_ts, horizon)
        if model is None:
            continue

        p_up = float(_predict_with_model(model, row))
        direction = "bullish" if p_up >= 50.0 else "bearish"
        target_ts = pd.Timestamp(source_ts) + pd.Timedelta(hours=int(horizon[:-1]))

        before = con.total_changes
        con.execute(
            """
            INSERT OR IGNORE INTO predictions (
                model_version, ticker, horizon,
                prediction_timestamp, source_bar_timestamp, target_timestamp,
                source_price, p_up, predicted_direction,
                feature_snapshot_json, training_samples,
                selected_l2, selected_shrink, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                MODEL_VERSION, ticker, horizon,
                iso(pd.Timestamp(source_ts)), iso(pd.Timestamp(source_ts)), iso(target_ts),
                source_price, p_up, direction,
                json.dumps(feature_snapshot(row), separators=(",", ":")),
                int(model.get("training_samples") or 0),
                float(model.get("selected_l2") or 0.0),
                float(model.get("shrink") or 0.0),
                iso(utcnow()),
            ),
        )
        if con.total_changes > before:
            inserted.append({"horizon": horizon, "p_up": p_up})

    con.commit()
    return {"ticker": ticker, "status": "ok", "source_bar": iso(pd.Timestamp(source_ts)), "inserted": inserted}


def nearest_target_bar(history, target_ts):
    if history.empty:
        return None, None
    idx = history.index
    target_ts = pd.Timestamp(target_ts)
    target_ts = target_ts.tz_localize("UTC") if target_ts.tzinfo is None else target_ts.tz_convert("UTC")
    diffs = np.abs((idx - target_ts).total_seconds())
    pos = int(np.argmin(diffs))
    if diffs[pos] > 15 * 60:
        return None, None
    ts = idx[pos]
    return ts, history.iloc[pos]


def settle_prediction(con, pred):
    source_ts = pd.Timestamp(pred["source_bar_timestamp"])
    target_ts = pd.Timestamp(pred["target_timestamp"])
    source_price = float(pred["source_price"])

    history = download_history(pred["ticker"], period="10d", interval="5m")
    if history.empty:
        return False

    target_bar_ts, target_row = nearest_target_bar(history, target_ts)
    if target_row is None:
        return False

    target_price = _series_value(target_row, history, "close")
    actual_return_pct = (target_price/source_price - 1.0)*100.0
    actual_up = int(target_price > source_price)
    predicted_up = int(float(pred["p_up"]) >= 50.0)
    correct = int(predicted_up == actual_up)

    p = min(max(float(pred["p_up"])/100.0, 1e-9), 1-1e-9)
    brier = (p-actual_up)**2
    log_loss = -(actual_up*math.log(p) + (1-actual_up)*math.log(1-p))

    window = history[(history.index > source_ts) & (history.index <= target_bar_ts)]
    mfe = mae = None
    if not window.empty:
        high = _frame_extreme(window, "high", "max")
        low = _frame_extreme(window, "low", "min")
        if high is not None and low is not None:
            high_ret = (high/source_price - 1.0)*100.0
            low_ret = (low/source_price - 1.0)*100.0
            if predicted_up:
                mfe, mae = high_ret, low_ret
            else:
                mfe, mae = -low_ret, -high_ret

    con.execute(
        """
        INSERT OR REPLACE INTO outcomes (
            prediction_id, settled_at, target_price, actual_return_pct,
            actual_up, correct, brier, log_loss, mfe_pct, mae_pct,
            target_bar_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(pred["id"]), iso(utcnow()), target_price, actual_return_pct,
            actual_up, correct, brier, log_loss, mfe, mae,
            iso(pd.Timestamp(target_bar_ts)),
        ),
    )
    con.commit()
    return True


def settle_due(con):
    rows = con.execute(
        """
        SELECT p.*
        FROM predictions p
        LEFT JOIN outcomes o ON o.prediction_id=p.id
        WHERE o.prediction_id IS NULL AND p.target_timestamp <= ?
        ORDER BY p.target_timestamp
        """,
        (iso(utcnow()),),
    ).fetchall()

    settled = 0
    for row in rows:
        try:
            settled += int(settle_prediction(con, row))
        except Exception as exc:
            print(f"  settle failed {row['ticker']} {row['horizon']}: {type(exc).__name__}: {exc}")
    return settled


def metrics(con):
    rows = con.execute(
        """
        SELECT p.horizon, p.p_up, o.correct, o.brier, o.log_loss
        FROM predictions p
        JOIN outcomes o ON o.prediction_id=p.id
        WHERE p.model_version=?
        """,
        (MODEL_VERSION,),
    ).fetchall()

    out = {}
    for horizon in HORIZONS_TO_COLLECT:
        h = [r for r in rows if r["horizon"] == horizon]
        if not h:
            out[horizon] = {"settled": 0}
        else:
            out[horizon] = {
                "settled": len(h),
                "accuracy_pct": round(100*sum(r["correct"] for r in h)/len(h), 3),
                "brier": round(sum(r["brier"] for r in h)/len(h), 5),
                "log_loss": round(sum(r["log_loss"] for r in h)/len(h), 5),
            }
    return out


def status(con):
    total = con.execute(
        "SELECT COUNT(*) AS n FROM predictions WHERE model_version=?",
        (MODEL_VERSION,),
    ).fetchone()["n"]
    settled = con.execute(
        """
        SELECT COUNT(*) AS n FROM outcomes o
        JOIN predictions p ON p.id=o.prediction_id
        WHERE p.model_version=?
        """,
        (MODEL_VERSION,),
    ).fetchone()["n"]
    return {
        "model_version": MODEL_VERSION,
        "database": str(DB_PATH),
        "predictions": total,
        "settled": settled,
        "pending": total-settled,
        "metrics": metrics(con),
    }


def collect_once(universe):
    con = connect()
    try:
        print(f"Settled due predictions: {settle_due(con)}")
        spy = download_history("SPY")
        if spy.empty:
            raise RuntimeError("SPY history unavailable.")

        inserted_total = 0
        for idx, ticker in enumerate(universe, 1):
            try:
                result = collect_ticker(con, ticker, spy)
                inserted = len(result.get("inserted") or [])
                inserted_total += inserted
                print(f"[{idx}/{len(universe)}] {ticker}: {result['status']} +{inserted}")
            except Exception as exc:
                print(f"[{idx}/{len(universe)}] {ticker}: FAILED {type(exc).__name__}: {exc}")

        print(f"New predictions inserted: {inserted_total}")
        print(json.dumps(status(con), indent=2))
    finally:
        con.close()


def loop(universe, interval_minutes):
    print("ORION V3 PROSPECTIVE VALIDATION COLLECTOR")
    print(f"DB: {DB_PATH}")
    print("Research-only. Stop with Ctrl+C. Existing data persists in SQLite.")
    print()
    while True:
        collect_once(universe)
        print(f"Sleeping {interval_minutes} minutes...\n")
        time.sleep(max(60, interval_minutes*60))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("once","loop","settle","status"))
    parser.add_argument("--interval-minutes", type=int, default=10)
    parser.add_argument("--tickers", nargs="*", default=list(DEFAULT_UNIVERSE))
    args = parser.parse_args()

    universe = []
    for ticker in args.tickers:
        t = ticker.strip().upper()
        if t and t not in universe:
            universe.append(t)

    if args.command == "once":
        collect_once(universe)
    elif args.command == "loop":
        loop(universe, args.interval_minutes)
    else:
        con = connect()
        try:
            if args.command == "settle":
                print(f"Settled: {settle_due(con)}")
            print(json.dumps(status(con), indent=2))
        finally:
            con.close()


if __name__ == "__main__":
    main()
