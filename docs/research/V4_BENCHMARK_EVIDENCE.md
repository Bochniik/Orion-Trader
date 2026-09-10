# Regular-hours V4 benchmark evidence

This document records the reproducibility policy for the offline V4 challenger tournament introduced after PR #22.

## Purpose

`backend/evals/benchmark_intraday_challenger_v4.py` compares the regime-aware V4 challenger against raw V3 and leakage-safe held-out V3.1 on exact paired out-of-sample timestamps. The benchmark is research-only and does not deploy or promote V4.

The canonical evidence runner is `scripts/run_intraday_v4_benchmark_evidence.py`.

## Evidence contract

The evidence runner wraps the existing benchmark without changing its model or gate logic. It intercepts every `yfinance.download` call made by the benchmark and records a SHA-256 fingerprint of the exact dataframe returned to the benchmark, together with symbol, row count, first/last index, period, interval, `auto_adjust` and `prepost` settings.

It also fingerprints the core V3/V3.1/V4 benchmark and inference source files, records the Git commit and Python runtime, hashes the complete benchmark result, and emits the research conclusion under the `orion-intraday-v4-benchmark-evidence-v1` contract.

The runner fails closed if the required SPY reference frame or any requested symbol is not observed in the captured provider calls. `promotion_allowed` is always false: a passing historical tournament is evidence for forward-shadow review only, never deployment authority.

## Recommended frozen benchmark

Run from the repository root with the candidate universe and parameters fixed before reading the result:

```bash
python scripts/run_intraday_v4_benchmark_evidence.py \
  AAPL MSFT NVDA AMZN META GOOGL TSLA AMD SPY QQQ \
  --period 60d --interval 5m \
  --calibration-fraction 0.60 \
  --min-symbols-per-horizon 3 \
  --min-observations 80 --min-sessions 8 \
  --bootstrap-samples 2000 \
  --output artifacts/intraday-v4-benchmark-evidence.json
```

Do not change the universe, thresholds or bootstrap policy after inspecting the result merely to obtain a passing conclusion. A failed benchmark should be retained as negative evidence and analyzed by horizon/regime before designing another challenger.

## Next logical step

Execute the frozen real-data benchmark and preserve its evidence JSON. If V4 does not beat both V3 and V3.1 across every required horizon under the existing proper-score and session-stability gates, reject V4 unchanged. If it passes, only then add V4 to forward cloud-shadow comparison; do not replace the incumbent runtime from historical evidence alone.
