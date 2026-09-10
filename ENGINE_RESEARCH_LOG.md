# OrionTrader Engine Research Log

This log tracks autonomous analytical-engine work separately from UI/product work.
Changes recorded here are research/evaluation infrastructure unless explicitly stated otherwise.

## 2026-09-10 — Cloud shadow evidence collection

### Premarket v5 cloud shadow

Merged PR #15 (`092fb1c06bb9b7b85b07b9b3feb03f94dd75a221`). The runner can collect causal Alpaca IEX history, rebuild the v2 training dataset and v5 artifact, and emit immutable 5m/15m/30m shadow forecasts without requiring a local Orion process. Predictions include data/model/code lineage and are research-only with order submission disabled.

The scheduled workflow is the first path to genuine timestamped out-of-sample Premarket v5 evidence. The next evaluation milestone remains Issue #3: settle enough predictions against later observed prices and score Brier/log loss/calibration/accuracy without using future information during prediction.

### Regular-hours V3.1 cloud shadow candidate

Branch `autonomous/2026-09-10-regular-hours-cloud-shadow` adds an analogous research-only runner around the existing V3.1 runtime.

Design constraints:
- New York regular-session gate is DST-safe and permits predictions only from 09:30 through 15:30 ET.
- The existing V3.1 reliability/suppression policy is preserved; low-reliability horizons are not restored or fabricated by the shadow layer.
- Individual symbol/provider failures are recorded without silently converting them into predictions.
- Each artifact records the Git commit and SHA-256 fingerprints of the core inference files.
- `order_submission_enabled` is hard-coded false and the runner has no broker/order imports.
- The cloud schedule is hourly and intentionally spans a wider UTC range; the Python New York-time gate skips runs outside the valid window across EDT/EST.

Validation target before merge:
- compile the new runner and V3.1 inference path;
- pass focused tests for symbol normalization, EDT/EST gating, session-boundary rejection, suppression provenance and partial provider failures;
- do not change runtime reliability tables, model thresholds or execution behavior.

### Next logical engine step

After both cloud shadow paths produce artifacts reliably, add a settlement/aggregation layer that scores only forecasts whose horizons have fully elapsed. The evaluator should retain prediction-time lineage and report per-symbol/per-horizon Brier score, log loss, calibration error, accuracy, coverage and reliability-profile source. No calibration or model candidate should be promoted from these shadow results until sample-size and stability gates are met.
