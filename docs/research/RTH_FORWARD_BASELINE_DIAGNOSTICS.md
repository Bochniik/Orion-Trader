# RTH forward baseline diagnostics

## Motivation

Settled Regular-hours V3.1 forward evidence has repeatedly shown that directional accuracy alone is not a sufficient promotion signal. A probabilistic engine must add information relative to simple causal baselines under proper scoring rules.

## Diagnostic contract

`backend/evals/rth_forward_baseline_diagnostics.py` compares the immutable settled RTH ledger against two baselines, globally and independently per horizon:

- neutral 50/50 probability;
- a chronological expanding prior estimated only from outcomes at strictly earlier prediction timestamps.

The expanding prior is timestamp-grouped. All symbols sharing a prediction timestamp receive the same prior before any outcomes from that timestamp are admitted to history. This prevents cross-sectional same-timestamp leakage when multiple symbols settle together.

The report includes Brier score, binary log loss, directional accuracy, model-minus-baseline proper-score deltas, and explicit booleans for whether the incumbent beats each baseline on both proper scores.

## Safety

This evaluator is research-only. It does not modify runtime inference, calibration, thresholds, risk policy, brokerage behavior, or model artifacts. Its promotion gate is deliberately fail-closed: evidence used to diagnose a model cannot promote a candidate designed from the same evidence. Any challenger informed by this report requires a new identity and later preregistered forward evidence.

## Regression coverage

Focused tests verify invalid-contract rejection, conflicting duplicate rejection, exact same-timestamp leakage prevention, proper-score deltas, fail-closed promotion semantics, and independent horizon scoring.

## Next decision

Use the cumulative immutable RTH ledger to identify whether the incumbent's deficit versus the chronological prior is persistent by horizon. If a challenger is designed from that diagnostic, freeze its identity before collecting new forward observations and require improvement in both Brier score and binary log loss rather than accuracy alone.
