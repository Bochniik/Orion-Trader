# OrionTrader 3.2 — deterministic research opportunities

## What changed

The existing scanner already provided broker-universe rotation, staged liquidity
screening, intraday features, experimental logistic/stump probabilities and
market-intelligence categories. This release reuses those paths and adds:

- Horizon-specific, bullish/bearish technical plans with a point-by-point audit.
- Cross-page research ranking, independent of the old model finalist list.
- Immutable per-user setup history and separately stored forward outcomes.
- Outcome summaries with explicit pending, no-entry and ambiguity exclusions.
- Compact Day / Swing / Long-Term controls under TODAY → Orion Picks.
- Optional Orion explanations of stored evidence, without replacing its numbers.

Neutral evidence is rejected rather than forced into a directional plan. Every
plan remains research-only, `final_decision=NO_TRADE`, `actionable=false`.
No orders, new provider, model retraining or probability-weight changes were added.

## Coverage, screening and bounded work

The connected Alpaca active/tradable US-equity universe remains the source of
discovery; a watchlist is not the universe. Existing pages default to 250 symbols.
Up to 15 liquidity-qualified symbols per page receive the new deeper analysis,
ordered by average dollar volume, including quiet symbols before the activity
gate. Daily data and SPY are reused through the existing provider cache. Up to
five due historical tickers are revisited independently of today's ranking.

Gates include existing quality checks, price >= $5, average daily dollar volume
>= $25M, session dollar volume >= $1M, at least 10 completed daily observations,
known spread <= 0.15%, and quote age <= 120 seconds. These can exclude early-session
stocks. Day features expire at 1,200 seconds; completed daily features at seven
days. Unavailable, malformed, future, unsorted or duplicate evidence fails closed.
Up to 300 research rows are retained across pages, with top 10 per horizon exposed.
This is partial rotating coverage, not a simultaneous scan of the entire market.

Closed-session market-intelligence behavior from 3.1 is retained. Historical
categories may be shown, but old research plans are stale, not current signals.

## Features and exact quality model

| Profile | EMA fast/slow | SMA | Momentum bars | Structural bars | Holding horizon |
| --- | --- | --- | --- | --- | --- |
| Day | 9/20 | 50 | 5 | 20 | 60 minutes |
| Swing | 20/50 | 100 | 20 | 30 | 10 sessions |
| Long-Term | 50/100 | 200 | 60 | 63 | 63 sessions |

Day uses completed one-minute bars; the other profiles use completed daily bars
mapped to actual exchange-session close times. Additional evidence: three-bar
EMA/SMA slopes, existing RSI14/ATR14 calculations, MACD12/26 with EMA9 signal,
bar volume relative to the previous 20-bar mean, 20-bar efficiency-ratio trend
strength, prior support/resistance excluding the decision bar, five-bar range
contraction and ATR contraction. VWAP is session VWAP for day and explicitly
rolling 20-session volume-weighted typical price for daily profiles. The existing
regime classifier receives contemporaneous SPY evidence; missing benchmark fails.

Bias = (2 sign(EMAfast−EMAslow) + sign(EMA slope) + sign(SMA slope)
+ sign(momentum) + sign(MACD histogram)) / 6.
Bias >= 0.5 is bullish; <= −0.5 bearish; otherwise neutral.

Quality = sum(weight × normalized confirmation). Weights total 100:

| Evidence | Day | Swing | Long-Term |
| --- | ---: | ---: | ---: |
| EMA/SMA trend | 16 | 22 | 30 |
| Momentum | 16 | 12 | 8 |
| RSI | 8 | 6 | 4 |
| MACD | 10 | 10 | 8 |
| Relative volume | 12 | 10 | 8 |
| VWAP | 10 | 4 | 2 |
| Entry structure | 10 | 14 | 16 |
| Trend strength | 6 | 8 | 10 |
| Liquidity | 6 | 8 | 8 |
| Market regime | 6 | 6 | 6 |

Each result contains normalized inputs, points and weights. Trend averages four
directional confirmations; RSI confirms 45–72 bullish / 28–55 bearish; volume is
capped at relative-volume/1.5; strength at efficiency/0.6. Structure contributes
1 for breakout, 0.8 for a trend pullback, 0.4 otherwise. Regime contributes 1 when
aligned, 0.5 in range/low-volatility, zero otherwise. Quality minimum is 70, or 75
below $100M average dollar volume. Unconfirmed structure, insufficient relative
volume, high-volatility regime, overextended price and unsuitable risk are rejected.

Entry zone is current price ±0.1 ATR. Structural stops include a 0.1 ATR buffer
and a profile minimum of 1.25/1.5/2 ATR; distance above 6 ATR is rejected. Targets
are 2R/3R from the worst entry-zone edge. Round-trip cost assumes one spread plus
0.05 ATR slippage per side. Post-cost reward/risk must be >=1.5. These are
hypothetical levels, not fill guarantees or calibrated target-hit probabilities.

## Confidence is not quality

Quality is an unvalidated deterministic score, NOT a percentage chance of profit.
Where the existing inference supplies compatible five-minute probabilities, they
are retained verbatim for day research and their horizon is shown separately.
A directional probability below 55% rejects that model-backed plan. An expired
five-minute forecast is suppressed. It never becomes a 60-minute success forecast.
Swing and Long-Term confidence remain unavailable without a compatible model.
No model is presented as statistically reliable. The 63-session technical profile
is not fundamental valuation or a complete long-term investment thesis.

## Persistence and evaluation

Additive SQLite tables in each user's existing database:
`research_setups`, `research_setup_outcomes`, `research_setup_attempts`.
Setup and outcome updates are blocked. Duplicate keys hash ticker, profile,
engine version, feature timestamp, source/quote timestamps, direction, strategy
and model identifier. A genuinely newer quote can create a new plan even when
the completed daily feature bar has not changed.
Repeat refreshes return the originally captured plan, not rewritten prices.
Engine version includes a deterministic hash of the profile configuration.

Setup payloads preserve timestamps, reference/entry/stop/targets, feature and
screening snapshots, model output when available, score audit, provenance, regime
and assumptions. Outcomes are separate append-only records; attempts hold pending
reasons without modifying prediction-time values.

Day simulation starts at the next minute boundary strictly after capture, using
the following bar's actual Open, only inside the frozen entry zone. Daily profiles
start at the next session Open after capture. All required one-minute/session bars
must exist. Missing paths are pending, never interpolated. Cross-session day plans
and changed historical adjustment bases are unresolved. Stops are gap-aware;
if stop and target occur in the same bar, ordering is ambiguous and the result is
excluded from headline trade statistics. Target 2 is a recorded touch, not a second
executed fill. MFE/MAE cover the full holding window, including after simulated exit.

Statistics cover the latest 5,000 captured plans and disclose truncation. Win rate
is net R > 0; expectancy is mean net R; average R is mean gross R. Strategy, regime,
direction, horizon and quality buckets are reported. Separate directional precision
includes resolved no-entry cases to avoid conditioning it only on simulated fills;
its label is the sign of the frozen reference-price return, not the existing
noise-adjusted directional-model class. Empty samples return null metrics.

Probability calibration is explicitly unavailable here: five-minute forecasts
cannot be calibrated against 60-minute/10-session/63-session outcomes. Quality
buckets are not probability calibration. Overlapping plans are not independent.
There is no asserted predictive edge or self-updating model.

## APIs and UI

- `GET /scanner/current` includes `research_opportunities` for existing polling.
- `GET /scanner/opportunities` returns the same read-only research state.
- `GET /scanner/opportunities/history?limit=100` returns captured plans/outcomes.
- `GET /scanner/opportunities/analytics` returns descriptive, unvalidated summaries.
- `POST /scanner/opportunities/{setup_id}/explain` explains the authenticated user's
  persisted evidence; client-supplied numbers are not accepted as replacements.

GET requests never trigger provider scans. History is loaded explicitly from
TODAY → Orion Picks. Selecting a ticker uses the existing Analyze workflow.
The existing Orion explanation guard rejects numeric prose; authoritative values
remain in the deterministic result. There is no connection to order submission.

## Limitations and operating requirements

Alpaca research connectivity and available Yahoo history are still required for
this production scanner; no standalone Yahoo universe was invented. Yahoo data
are delayed and limited; historical adjustment changes, missing bars and expired
intraday history can leave outcomes unresolved/pending. Pending attempts are
revisited during running scanner cycles, not by a new worker. Keep the backend
running and broker connected; recovery uses persisted plans after restart.
No quote queue, historical executable NBBO, precise intrabar ordering, commissions,
borrow availability or borrow cost is established. Existing directional-model
training and settlement modules were not changed by this release.

## Validation

Targeted backend tests: 259 passed, including 42 new scoring/journal/integration
cases. Targeted frontend tests: 71 passed across six files, including five new
research-panel cases. Production Vite build and changed-Python compilation
passed. No repository-wide suite or fresh dependency-security audit was run.
An isolated real backend process returned HTTP 200 from `/health` and `/ready`
with version 3.2.0, required authentication for scanner routes, and shut down both
background loops cleanly. No configured broker users were available in the test
environment, so this is not a live-account market-data verification.
Provider integration tests use deterministic data, not manufactured real performance.

## Install

Stop the old backend first. Extract the ZIP; the application is inside its
`OrionTrader` folder. Preserve your existing `backend/.env` and application user
data directory when migrating; do not delete databases. Tables are added safely.
From the folder containing `start-orion.ps1`, run the existing launcher. If your
personal Windows execution policy blocks a trusted downloaded script, you can
launch it for that process only with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-orion.ps1
```

This does not alter a permanent execution policy; managed policy may still block
it. Start only the script from the archive you intended to trust.
