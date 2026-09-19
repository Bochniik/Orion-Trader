# Orion 24/7 Intelligence

Milestone issue: #141

## Purpose

Orion remains useful when the NYSE regular session is not open by changing workflow rather than presenting stale evidence as live. The milestone reuses the existing Premarket, Regular-hours, scanner, learning, settlement, market-intelligence, news/catalyst and research layers; it does not create a second prediction system.

## Session-state contract v2

`orion-session-state-v2` is the central backend contract. It exposes regular / premarket / after-hours / closed mode, workflow and UI priority, explicit price semantics, regular open/close and next open, next transition, calendar verification, warnings and allowed workflows. Broker clock/calendar evidence remains authoritative and failures degrade conservatively toward research rather than live mode.

## Dashboard behavior

The frontend reads `GET /core/session`. Outside regular hours Today presents the Orion 24/7 research workspace, next regular session, watchlist research queue, settlement/evaluation state and explicit price semantics instead of an empty live card.

## Daily close learning review

The first follow-up slice adds `GET /scanner/learning/daily-close-review?session_date=YYYY-MM-DD`. It reads only already-settled empirical forecasts belonging to the authenticated user and assigns them to the requested session using `America/New_York`, avoiding UTC-midnight misclassification.

The `orion-daily-close-review-v1` contract reports settled count, Brier score, binary log loss, directional accuracy, false-positive/false-negative counts and proper scores by forecast horizon. Invalid probabilities and malformed timestamps fail visible through diagnostics and are never converted into fabricated metrics. Slices such as liquidity and sector are explicitly reported as missing when the persisted evidence does not contain those dimensions.

This report is observational. It does not retrain, recalibrate, promote a challenger, change thresholds or alter production decisions. It therefore remains compatible with the existing leakage-safe research and promotion gates.

## Safety

- No production model weights, probabilities, calibration or trade gates change.
- No order path or live-trading capability is added.
- Premarket and after-hours remain research/transition modes.
- Closed-market prices are never labelled as live regular-session data.
- Missing data produces unavailable/diagnostic output rather than invented evidence.
- Existing challenger preregistration and promotion gates remain authoritative.

## Next slices

1. Surface the daily close review in the closed-market dashboard once endpoint CI is green.
2. Overnight watchlist review using completed-session research + news.
3. Next-session briefing and deterministic scenario planner.
4. Native catalyst prioritization and thesis-impact classification.
5. Earnings/catalyst calendar and sector/regime review.
6. Closed-market research-lab orchestration using existing evaluation and challenger gates.
