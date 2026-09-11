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

## Forward evidence readiness rule

The pre-registered forward gate now also distinguishes an **immature forward sample** from an actual model failure. This is necessary because the post-registration holdout starts empty and must accumulate naturally; interpreting a sub-threshold sample as `long_horizon_challenger_not_demonstrated` would repeat the same geometry mistake in a different form.

For each required horizon, the gate exposes only score-blind readiness fields before model quality is interpreted:

- current paired observation count,
- the frozen minimum observation requirement,
- observations still required,
- current distinct-session count,
- the frozen minimum session requirement,
- sessions still required.

If all paired timestamps are post-cutoff but either `3h` or `5h` is still below the pre-registered coverage thresholds, the disposition is:

`forward_holdout_collecting_evidence`

Only once both horizons are coverage-mature can a negative paired tournament result become:

`long_horizon_challenger_not_demonstrated`

This does **not** weaken the statistical thresholds, inspect scores to decide when to stop collecting, or modify V5. It prevents sample-size immaturity from masquerading as evidence against the model.

## Next logical step

Accumulate untouched post-registration paired 3h/5h shadow observations until the existing `80` observations / `8` distinct sessions gate is genuinely mature for both horizons and both incumbent comparisons. Do not stop early because interim scores look favorable or unfavorable. Once the score-blind readiness gate is mature, run the frozen paired tournament exactly once for the decision-grade forward holdout. Runtime models, risk policy, thresholds, broker behavior and order paths remain unchanged until decision-grade evidence exists.
