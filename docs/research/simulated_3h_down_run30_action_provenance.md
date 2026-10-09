# SIMULATED_FORWARD 3h DOWN research — run #30 (2026-10-09)

Read-only audit of GitHub Actions run 37873487734 (state artifact 11592137612) and preregistered challenger run 37875864967 (artifact 11592640641).

## Correct action semantics

The legacy challenger evaluator interprets `probability_up >= 0.5` as an issued trade, including persisted `direction=neutral` predictions. This is not valid for a NO_TRADE policy. From 384 later-by-prediction-time settled directional rows (one NY trading day), persisted actions were **250 neutral, 109 bullish, 25 bearish**.

- Incumbent issued trades: **134**, accuracy **101/134 = 75.37%**, coverage **34.90%**.
- Challenger retaining issued bullish trades: **109**, accuracy **80/109 = 73.39%**, coverage **28.39%**.
- Avoided bearish actions: **25**, of which **21 were correct** (84.0%). Issued-action accuracy change: **−1.98 percentage points**.
- The legacy report instead counts 228 trades at 67.98% accuracy, because neutral actions are misclassified as trades.
- The preregistered minimum coverage is 30%, minimum avoided count is 50, and minimum market-day count is 5. These are **not met**; do not loosen them.

## Issuance chronology and independent evidence

All **384** candidate rows were created **after their target timestamps**. Later `prediction_time_utc` does **not** establish prospective issuance. The source is historical SIMULATED_FORWARD replay, not independent later-unseen OOS evidence. There are **zero** independently attested prospective OOS samples.

## Full cloud learning

Run #30 added **8,735** predictions relative to run #29, of which **8,280** are settled and **8,272** are directionally scorable. No historical forecast was changed. All new predictions were created after their target time. Run #30 finished all 10 replay symbols.

Maturity-purged chronological walk-forward still fails:
- 3h Brier improvement **−0.001681**, fold pass rate **40.96%**.
- 5h Brier improvement **−0.003023**, fold pass rate **26.03%**.

The learning summary's `promotable_horizons: ["3h"]` is only preliminary validation, **not** a promotion authorization. No challenger is approved. Do not mutate LIVE_FORWARD or production trading.

## Required implementation

Use persisted `direction` (bullish/bearish/neutral), enforce issuance provenance and a preregistered cutoff, group uncertainty by independent trading day, reject post-target historical replay as unseen evidence, and require independent attestation before any research challenger can be kept. NO_TRADE does not improve Brier by itself because probabilities are unchanged.

This note is descriptive research evidence, not a CI-tested production change.