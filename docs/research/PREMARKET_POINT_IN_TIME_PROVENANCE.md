# Premarket V5 point-in-time provenance gate

Status: research-integrity infrastructure only. This gate does not change Premarket V5 model weights, thresholds, calibration, collection cadence, runtime behavior, broker behavior, risk policy, or order paths.

## Why this exists

The existing dataset-readiness audit checks schema, snapshot timing, target boundaries, feature completeness and the 40/10/5 session geometry required by Premarket V5 validation. Those checks are necessary but are not sufficient to prove that the exact CSV being evaluated is the same content-addressed dataset produced from the recorded point-in-time raw collection.

Issue #3 requires decision-grade evidence from a real point-in-time dataset. A CSV copied, rebuilt, resumed or modified without a verifiable lineage chain must therefore fail closed rather than receive a readiness PASS based only on its columns and timestamps.

## Required lineage chain

The provenance audit requires all four artifacts to be present and mutually consistent:

1. Premarket training dataset CSV.
2. Dataset manifest written by `build_premarket_training_dataset_v2.py`.
3. Raw one-minute source CSV recorded by that dataset manifest.
4. Raw collection manifest written by `collect_alpaca_extended_history.py`.

The exact dataset bytes must match `dataset_csv_sha256`. The exact raw source bytes must match `source_csv_sha256` in the dataset manifest, and the raw collection manifest must match its recorded SHA-256. The source CSV identity must also agree between the raw collection manifest and the dataset manifest.

For decision-grade point-in-time validation, `source_lineage_status` must be `verified_source_manifest`. Legacy datasets built without a source manifest remain usable for exploratory diagnostics but are not accepted as decisive Issue #3 evidence.

## Frozen collector contract

The gate additionally verifies the data-collection contract expected by the current Premarket V5 pipeline:

- collector: `alpaca-extended-history-v2`;
- source: Alpaca stock bars v2;
- timeframe: one minute;
- adjustment: raw;
- timezone: `America/New_York`;
- retained local hours: 04:00-15:59;
- feed: IEX or SIP.

Contract drift fails closed. A future deliberate collector revision must receive an explicit new accepted contract rather than silently inheriting evidence eligibility.

## Relationship to dataset readiness

This provenance gate and `audit_premarket_dataset_readiness.py` answer different questions and both are required before a dataset should be treated as decision-grade:

- readiness: does the dataset have valid timing, features, labels and enough sessions for the frozen validation geometry?
- provenance: can the exact evaluated dataset be traced byte-for-byte to the exact recorded raw point-in-time collection under the expected collector contract?

Passing either gate alone is not model evidence and does not authorize deployment. Once both gates pass on a sufficiently large real dataset, the existing leakage-safe Premarket V5 walk-forward/event-nested validation can produce Brier, log-loss, calibration and stability evidence required by Issue #3.
