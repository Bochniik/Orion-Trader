# OrionTrader Engine Research Log

This log tracks autonomous analytical-engine work separately from UI/product work.
Changes recorded here are research/evaluation infrastructure unless explicitly stated otherwise.

## 2026-09-10 — Cloud shadow evidence collection

### Premarket v5 cloud shadow

Merged PR #15 (`092fb1c06bb9b7b85b07b9b3feb03f94dd75a221`). The runner can collect causal Alpaca IEX history, rebuild the v2 training dataset and v5 artifact, and emit immutable 5m/15m/30m shadow forecasts without requiring a local Orion process. Predictions include data/model/code lineage and are research-only with order submission disabled.

The scheduled workflow is the first path to genuine timestamped out-of-sample Premarket v5 evidence. The next evaluation milestone remains Issue #3: settle enough predictions against later observed prices and score Brier/log loss/calibration/accuracy without using future information during prediction.

### Regular-hours V3.1 cloud shadow

Merged commit `4d9d57ec74f4373e424ed6d215a1d1b1e0e6253f` adds an analogous research-only runner around the existing V3.1 runtime.

Design constraints:
- New York regular-session gate is DST-safe and permits predictions only from 09:30 through 15:30 ET.
- The existing V3.1 reliability/suppression policy is preserved; low-reliability horizons are not restored or fabricated by the shadow layer.
- Individual symbol/provider failures are recorded without silently converting them into predictions.
- Each artifact records the Git commit and SHA-256 fingerprints of the core inference files.
- `order_submission_enabled` is hard-coded false and the runner has no broker/order imports.
- The cloud schedule is hourly and intentionally spans a wider UTC range; the Python New York-time gate skips runs outside the valid window across EDT/EST.

## 2026-09-10 — Leakage-safe shadow settlement evaluator

Merged commit `9ba8317289b86b72fa2800c60348d0a6bcc7a489` adds a shared evaluator for Premarket v5 and Regular-hours V3.1 immutable shadow prediction artifacts.

Evaluation policy:
- A forecast is eligible only after its full horizon has elapsed at the evaluation cutoff.
- Base price is the latest one-minute bar at or before the prediction timestamp and is rejected if more than five minutes stale.
- Outcome price is the first one-minute bar at or after the target timestamp and is rejected if more than five minutes late.
- Suppressed Regular-hours V3.1 probabilities are excluded rather than reconstructed.
- Premarket `NO_TRADE` presentation does not erase the underlying probability forecast; research scoring retains the recorded raw direction and probability so model calibration can be audited independently from the decision layer.
- Prediction-time model/data/code lineage is copied into every settled record.
- Metrics include Brier score, binary log loss, directional accuracy, 10-bin expected calibration error, settlement coverage, and per-engine/per-horizon breakdowns.
- Missing/stale bars reduce coverage rather than being silently imputed.

Focused regression tests cover horizon parsing, probability normalization, suppression exclusion, lineage preservation, fully elapsed-horizon gating, stale/missing price rejection, and deterministic metric calculations.

## 2026-09-10 — Append-only shadow evidence ledger candidate

Branch `autonomous/2026-09-10-shadow-evidence-ledger` adds an idempotent accumulator for settled cloud-shadow evidence.

Evidence integrity policy:
- Every settled observation receives a deterministic SHA-256 identity based on engine, symbol, horizon, prediction timestamp, target timestamp and prediction-time lineage.
- Reprocessing the same evaluation or downloading the same artifact under a different local path does not duplicate an observation.
- If the same identity appears later with different material prediction or outcome fields, accumulation fails closed instead of silently replacing historical evidence.
- Prediction-time model/data/code lineage remains part of the identity, so otherwise identical forecasts from different model artifacts remain distinct research observations.
- Only evaluation payloads explicitly marked `leakage_safe=true` under the `orion-cloud-shadow-evaluation-v1` contract are accepted.
- Cumulative summaries report observation count, distinct prediction-session count, Brier score, log loss, directional accuracy and 10-bin ECE globally and by engine/horizon.
- The ledger does not decide model promotion and does not alter runtime thresholds, reliability tables or trading behavior.

Focused tests cover path-independent record identity, repeated-run idempotence, conflict detection, lineage separation, cumulative metrics, leakage-safe input enforcement and preservation of prior evidence.

### Next logical engine step

After the evidence ledger passes CI and merges, wire a scheduled research workflow that downloads prior immutable shadow artifacts, fetches only the bounded one-minute Alpaca outcome windows needed for fully elapsed forecasts, runs settlement, then accumulates the results into a versioned ledger artifact. Do not introduce promotion logic until enough distinct sessions exist to evaluate sample-size and fold stability. Issue #3 remains open until genuine point-in-time Premarket v5 observations satisfy the existing 40d train + 10d calibration + 5d test evidence requirement.
