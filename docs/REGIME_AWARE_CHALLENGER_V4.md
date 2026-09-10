# Regular-hours regime-aware challenger v4

## Research purpose

This candidate is deliberately different from the current regular-hours V3/V3.1 path. It is an offline-only challenger and does not change Orion runtime inference, thresholds, reliability profiles, risk policy, brokerage, leverage, or execution behavior.

## Model design

The challenger retains the causal V3 statistical feature vector and adds six regime terms: high-volatility and trending indicators plus interactions with 5-minute return, volume z-score, 30-minute relative strength, and VWAP distance. The regime cutoffs are estimated independently for every daily refit using only the eligible historical training rows. High volatility is defined by the historical 70th percentile of 30-minute realized volatility and trending by the historical 65th percentile of absolute trend slope.

Every test day is predicted by a model refit before that day's first evaluated timestamp. Training rows are limited to outcomes fully resolved before that point using the same horizon-specific cutoff semantics as V3. Probabilities are conservatively shrunk toward 50% and clipped to 3%-97%.

## Evaluation contract

`walk_forward_challenger_v4_frame(..., include_records=True)` emits the same `{timestamp, p_up, actual_up}` chronological OOS record contract as V3. This allows the paired challenger tournament to compare V3 and v4 only on identical timestamps and identical outcomes.

The candidate is not promoted merely because it exists or because synthetic regression tests pass. A real-data tournament must demonstrate positive Brier-score and log-loss improvement with sufficient observations/sessions and positive lower 95% session-block bootstrap bounds for every required horizon. Otherwise the candidate is rejected or redesigned.

## Regression guards

Focused tests verify regime thresholds are determined only by the supplied training sample, OOS record schema and probability bounds, exact timestamp/outcome pairing with V3, and that mutating a later unseen session cannot alter predictions from the first test session.

## Next step

Run V3 and challenger v4 over the same sufficiently long multi-symbol historical regular-hours dataset, then feed both OOS reports to `backend/evals/intraday_challenger_tournament.py`. Keep v4 research-only unless proper-score and session-level stability criteria are satisfied. Genuine forward cloud-shadow evidence remains a separate required validation layer before any runtime promotion.
