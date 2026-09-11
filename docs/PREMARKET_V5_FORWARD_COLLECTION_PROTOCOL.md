# Premarket V5 forward collection protocol

Pre-registered: 2026-09-11. This document freezes the collection cadence before early/mid/late outcomes are used to evaluate or tune Premarket V5.

## Purpose

Issue #3 requires genuine point-in-time Premarket V5 evidence across premarket regimes. The previous cloud shadow anchor collected only 09:15 ET (`late`) observations. This protocol broadens forward evidence collection without changing the model, thresholds, risk policy, promotion state, broker behavior, or order paths.

## Frozen cadence

Each US trading weekday has at most three active prediction snapshots:

- `early`: 06:45 ET
- `mid`: 08:00 ET
- `late`: 09:15 ET

The clocks are fixed in `America/New_York`. GitHub Actions declares both EDT and EST UTC cron slots. `scripts/resolve_premarket_v5_snapshot.py` activates exactly one matching UTC slot per regime/session and fails closed with `inactive_dst_slot` for the duplicate DST slot.

Do not move these clocks in response to Brier score, log loss, directional accuracy, calibration, confidence buckets, or individual trade outcomes. Any later cadence redesign must receive a new protocol identity and collect a new untouched forward sample.

## API/resource budget

The forward collector is bounded to:

- maximum 3 active Premarket V5 jobs per weekday/session;
- the existing 10-symbol research basket by default: AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ;
- Alpaca `iex` feed only; this change does not enable SIP or any paid data source;
- 120 calendar days of causal lookback per active snapshot, matching the existing cloud-shadow job;
- no order submission and no broker/order imports;
- inactive EDT/EST duplicate jobs terminate before dependency installation, credential checks, market-data download, training, or inference.

If this budget proves operationally excessive, collection may be reduced for cost/reliability reasons only. It must not be increased or selectively scheduled based on observed model performance without a new pre-registration.

## Leakage and data-quality rules

All existing cloud-shadow safeguards remain authoritative:

- prediction timestamps are frozen before market-data reconstruction;
- downloaded history is clipped to `timestamp <= as_of` before dataset construction or training;
- the runner requires a previous regular close and at least three causal premarket bars for a symbol;
- unavailable symbols remain explicitly unavailable instead of receiving fabricated predictions;
- immutable artifacts retain code/model/data lineage hashes;
- settlement waits for the complete horizon and rejects stale/missing base or outcome bars;
- regular-hours observations are not mixed into Premarket V5 regime metrics.

## Evaluation policy

The cadence itself is score-blind. Evidence should continue accumulating until sample size is sufficient for decision-grade evaluation. Metrics remain Brier score, binary log loss, directional accuracy, ECE/calibration, coverage, fitted temperature where applicable, and fold/session stability.

Results must be reported separately by `early` / `mid` / `late` regime and 5m / 15m / 30m horizon. Sparse cells are reported as insufficient evidence rather than pooled to manufacture significance.

No runtime promotion follows automatically from a favorable result. Promotion remains a separate reviewed decision.

## Next logical step

After this cadence has produced enough settled forward observations, audit collection coverage first without inspecting model scores. Only when regime/horizon cells are sufficiently populated should Issue #3 interpret proper-score and calibration results. If any regime is weak, diagnose feature availability, target geometry, calibration, and regime shift before changing thresholds or retraining.
