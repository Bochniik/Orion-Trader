# Causal Walk-Forward Contract

`backend/evals/causal_walk_forward.py` is the shared split boundary for Orion research models.

The `orion-causal-walk-forward-v1` contract creates four strictly ordered blocks in every fold:

1. expanding training history;
2. validation for model and hyperparameter selection;
3. calibration for probability calibration only;
4. untouched test evidence.

No shuffling is allowed.  Label intervals that reach the next block are purged from the left block,
and an optional wall-clock embargo removes observations immediately after each raw boundary.
Preprocessing, feature selection, denoising, model fitting and probability calibration must be fit by
the caller only on their designated blocks.  The untouched test block must never choose thresholds,
temperature or model variants.

`assert_fold_causality` independently verifies non-overlap, strict timestamp ordering and label-window
separation.  `fold_manifest` emits the exact observation counts and UTC ranges needed by evaluation
artifacts.  A split that loses an entire required block fails closed rather than silently weakening the
protocol.

This module does not promote a challenger or alter runtime predictions.  Existing model-specific
validators should migrate to this shared contract incrementally and retain their current production
boundaries until a forward-only tournament accepts a replacement.
