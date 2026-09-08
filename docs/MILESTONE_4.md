# Milestone 4 — Unified decision radar

Version `2.4.0`, 2026-09-02.

This release turns the Today workflow into a staged, liquidity-first Opportunity Radar. It reuses the existing calibrated logistic and boosted-stump baselines, 14 deterministic strategy families, regime classifier, cost-aware expected value and per-user outcome memory. The AI layer remains explanatory only.

Directional probability and trade permission are now separate fields. A valid model probability remains visible when a liquidity, cost, freshness, model-validation or market-hours gate returns WAIT. If probabilities are incomplete, Orion reports that exact contract failure. No entry, invalidation or target is issued for a blocked result.

Radar categories are built from fetched deterministic evidence: Orion Picks, biggest gainers and losers, most active by current dollar volume, unusual volume, inferred quote buy/sell pressure, momentum leaders, potential bargains only when RSI/VWAP dislocation evidence exists, and breakout watch. Market pressure is never described as broker-customer buying or selling. Missing fields keep a symbol out of the category.

Today refreshes at a bounded 30-second interval only while the page is visible and the user leaves auto-refresh enabled. It never requests a full-universe scan every few seconds. Orion Prime is optional and normally absent: it requires Tier A liquidity, at least 75% directional probability, at least 75 agreement, opportunity score at least 80, post-cost edge at least 10 bps, a supportive regime, known execution cost and no blockers. Visual highlighting is always available; sound is opt-in and a 15-minute server-side signature cooldown prevents repeated alerts.

The application remains assistant-only. There is no automatic order execution, no claim of certainty, no customer-flow feed, and no assertion that a Prime alert is profitable. Existing point-in-time outcome capture and descriptive quality reporting from 2.3 remain authoritative.
