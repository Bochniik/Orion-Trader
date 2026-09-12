# Regular-hours forward evidence retention

## Decision

Regular-hours V3.1 cloud-shadow artifacts are retained for at least **90 days**.

## Why 30 days was insufficient

The regular-hours pipeline is being evaluated as a forward, point-in-time research system. A 30-day artifact window can expire the earliest observations before enough distinct market sessions exist for stable calibration, proper-score, horizon, regime, and provenance analyses. It also makes cross-session investigations of scheduler delivery and source timestamp alignment unnecessarily fragile.

A 90-day window gives the research pipeline enough evidence durability to accumulate a multi-week forward sample while remaining bounded. This matches the conservative durability policy already used for Premarket V5 evidence.

## Contract

The workflow `.github/workflows/regular-hours-v3-1-cloud-shadow.yml` must declare `retention-days >= 90` for the immutable shadow artifact upload.

`backend/tests/test_regular_hours_evidence_retention.py` protects this requirement and is part of the focused Regular-hours cloud-shadow CI suite.

## Safety boundary

This change does not alter model inputs, model weights, probabilities, calibration, decision thresholds, market-data providers, session windows, risk logic, broker behavior, order submission, or live trading. It only preserves research evidence longer.

## Next step

Use future in-session runs to measure provenance-valid coverage and scheduler delivery quality over multiple distinct NYSE sessions. Do not tune model thresholds based on a short or selectively retained sample.
