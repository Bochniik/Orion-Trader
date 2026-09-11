# V5 historical-screen protocol audit

## Status

The first frozen long-horizon V5 historical evidence run completed successfully at the workflow level and preserved data/code provenance. Its raw benchmark conclusion was `v5_reject_unchanged`.

A score-blind audit of the validation geometry found that this conclusion is **not decision-grade** against V3.1 under the frozen thresholds.

## Why the protocol was infeasible

The frozen workflow used:

- `60d` / `5m` regular-hours data,
- V3.1 calibration fraction `0.60`,
- minimum `80` paired observations per symbol and horizon,
- minimum `3` symbols capable of satisfying the per-symbol tournament gate.

Across all ten symbols in the captured evidence, the leakage-safe V3.1 evaluation holdout produced exactly:

- `72` paired observations per symbol for `3h`,
- `36` paired observations per symbol for `5h`.

Therefore **zero of ten symbols** could satisfy the configured `min_observations=80` requirement against V3.1 on either horizon. The aggregate benchmark could still compute Brier/log-loss deltas, but `stable_symbols` was structurally forced to zero because a per-symbol tournament verdict cannot become `research_eligible` when coverage is below its own minimum.

This is a validation-protocol bug, not evidence that V5 is good or bad.

## Frozen evidence still matters

The frozen artifact must not be discarded or rewritten. It remains useful evidence that:

- the data pipeline and provenance capture worked,
- aggregate proper-score deltas were positive for V5 on both 3h and 5h against V3 and V3.1,
- session-level/per-symbol stability was not demonstrated under the frozen gate,
- the V3.1 branch of that stability gate was impossible to satisfy with the available holdout geometry.

Because the protocol was infeasible, the correct disposition is:

`benchmark_inconclusive_protocol_infeasible`

not model promotion and not model rejection.

## Anti-overfitting rule

Do **not** lower `min_observations`, change calibration fraction, retune V5, or otherwise alter the frozen test after seeing these outcomes and then use the same data to approve the candidate. That would turn a protocol repair into post-hoc model selection.

Any replacement protocol must be specified before evaluating a new untouched holdout.

## Code change

`backend/evals/audit_long_horizon_screening_protocol.py` adds a score-blind feasibility audit. It checks only whether enough symbols had enough paired V3.1 observations to be capable of satisfying the configured tournament coverage rule. It intentionally ignores Brier score, log loss, accuracy, ECE and bootstrap outcomes.

Future V5 evidence payloads embed this audit and expose a top-level `decision_grade` flag. A benchmark that cannot satisfy its own coverage geometry is explicitly marked non-decision-grade even if the underlying scoring job completes successfully.

## Next logical step

Design and pre-register a **feasible** long-horizon validation geometry using untouched future data. Prefer changing the evidence horizon/collection duration rather than weakening statistical thresholds after outcome inspection. Once enough new 3h/5h paired observations exist, evaluate the frozen candidate and incumbent under the pre-registered gate. Runtime models, risk policy, thresholds, broker behavior and order paths remain unchanged until decision-grade evidence exists.
