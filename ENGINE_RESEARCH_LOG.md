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

## 2026-09-10 — Leakage-safe shadow settlement evaluator candidate

Branch `autonomous/2026-09-10-shadow-settlement-evaluator` adds a shared evaluator for Premarket v5 and Regular-hours V3.1 immutable shadow prediction artifacts.

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

### Next logical engine step

After the evaluator is merged, connect it to downloaded immutable GitHub Actions shadow artifacts plus a bounded Alpaca 1-minute outcome collection window. Accumulate results across sessions without overwriting prior evidence, then add sample-size and stability gates before any model/reliability profile can be promoted. Issue #3 remains open until enough genuine point-in-time Premarket v5 observations exist to evaluate the existing 40d train + 10d calibration + 5d test policy with meaningful OOS diagnostics.
