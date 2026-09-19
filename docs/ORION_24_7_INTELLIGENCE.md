# Orion 24/7 Intelligence

Milestone issue: #141

## Purpose

Orion should remain useful when the NYSE regular session is not open. Outside
regular hours the application changes workflow instead of presenting stale
regular-session evidence as live.

This milestone reuses the existing Premarket, Regular-hours, scanner, learning,
settlement, market-intelligence, news/catalyst and research layers. It does not
create a second prediction or learning system.

## Existing capabilities found during the audit

Orion already has:
- a deterministic `market_session_engine.py` with premarket / regular /
  after-hours / closed modes;
- Alpaca clock and calendar access;
- a dedicated Premarket research path;
- Regular-hours predictive/evidence pipelines;
- completed-session market scanning;
- empirical learning memory and settlement/evaluation;
- market-regime and market-intelligence services;
- watchlist persistence;
- news/catalyst analysis and optional Orion AI news explanations;
- strategy research and backtesting.

The main architectural gap was that Core still had a second hard-coded session
classifier and Today treated a closed regular session as an empty live scan.

## Session-state contract v2

`orion-session-state-v2` is the central backend contract. It exposes:

- `mode`: regular / premarket / after_hours / closed;
- `workflow_mode`: live / transition_research / research;
- `ui_priority`: the work the dashboard should prioritize;
- `price_semantics`: live_regular / extended_hours /
  historical_or_delayed;
- regular open/close and next regular open;
- next transition and transition kind;
- calendar verification and warnings;
- allowed workflows such as live scanning, premarket research, settlement,
  research laboratory and next-session preparation.

The broker clock is authoritative for whether the regular market is open. The
broker NYSE calendar is passed into the shared classifier so holidays and early
closes are not inferred from weekday/hour rules. Calendar failure degrades
conservatively.

## Dashboard behavior

The frontend reads `GET /core/session` alongside existing cached market state.
When regular hours are closed, Today displays an Orion 24/7 research workspace
instead of an empty live card. It shows the next regular session in the user's
browser-local time, the saved watchlist research queue, whether the
settlement/evaluation window is active and explicit price semantics.

This first slice does not claim that overnight watchlist review, catalyst
ranking, next-session scenario planning or the full daily learning report are
complete. Those remain tracked under #141 and should land independently.

## Safety

- No production model weights, probabilities, calibration or trade gates change.
- No order path or live-trading capability is added.
- Premarket and after-hours are research/transition modes.
- Closed-market prices are never labelled as live regular-session data.
- Missing calendar/session data fails toward research/diagnostics, not live mode.
- Existing leakage-safe challenger and promotion gates remain authoritative.

## Next slices

1. Daily close review assembled from existing settled evidence.
2. Overnight watchlist review using completed-session research + news.
3. Next-session briefing and deterministic scenario planner.
4. Native catalyst prioritization and thesis-impact classification.
5. Earnings/catalyst calendar and sector/regime review.
6. Closed-market research-lab orchestration using existing evaluation and
   challenger gates.
