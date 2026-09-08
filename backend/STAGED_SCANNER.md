# Task 5A1 — staged market scanner core

This milestone adds a one-shot backend discovery service. It does not add a UI,
HTTP endpoint, scanner loop, alerts, new indicators/models, training, prediction
storage, or settlement changes. The existing application version strings remain
unchanged; `OrionTrader-2.6.zip` is the incremental source delivery.

## Invocation and contracts

`StagedMarketScanner(source, analyzer, config).scan_market(tickers=None, now=None,
universe_offset=0)` accepts any finite iterable of ticker strings. It normalizes,
deduplicates, sorts and pages the supplied universe. A fixed timezone-aware `now`
provides a deterministic cutoff for tests. Without it, freshness is checked at
retrieval time and again before inference, so a long scan cannot silently age
evidence out. There is no timer or background execution.

The source interface is limited to `stock_universe`, `load_screening_batch` and
`load_feature_snapshots`. The analyzer receives the already-computed feature
snapshot, screening evidence, requested horizons and evaluation time.

Production invocation uses already configured, user-scoped clients and an
already fitted model; it does not obtain credentials or build a baseline:

```python
from app.services.staged_scanner_adapters import scan_with_existing_services
from app.services.staged_market_scanner import ScannerConfig

result = scan_with_existing_services(
    market_data=market_data,
    alpaca_broker=alpaca_broker,
    user_id=user_id,
    model=predictive_store.latest_model(),
    # Omit tickers to use the connected broker's active tradable universe.
    tickers=selected_ticker_iterable,
    config=ScannerConfig(),
)
```

## Universe and staged budgets

The default source reuses `AlpacaBroker.assets`: active, tradable US equities
available through that connection. It is not asserted to be a complete US
listing universe. Custom supplied tickers can come from another existing
universe source; snapshots still require the configured Alpaca connection.

| Stage | Default limit / rule |
| --- | --- |
| Universe page | 1,000 unique symbols, alphabetically; explicit `next_offset` |
| Screening | Batches of 100 IEX snapshots plus one-month daily history |
| Data quality | Required fields and freshness; at least 10 completed daily sessions |
| Hard liquidity | Dollar-volume / price minimums; spread ceiling if measured |
| Activity | Score at least 15, retain top 100 |
| Minute features | Load only activity finalists plus one shared SPY benchmark |
| Fast score | At least 20, retain top 30 |
| Directional inference | At most 15 symbols; default horizon `5m` |
| Output | At most 10 symbol/horizon results |

Configuration requires return <= analysis <= fast <= activity <= universe.
Absolute safety ceilings are 200 symbols/snapshot call, 10,000 symbols/page and
100 full-analysis symbols. Multiple requested horizons each consume one model
evaluation; the maximum is `analysis_limit * len(horizons)`.

The existing minute-history transport silently caps a request at 50 symbols.
The adapter splits larger finalist lists explicitly, reuses each downloaded
history and computes features once per symbol. No full inference is run on the
entire universe. Paging is explicit, not an automatically rotating scanner yet.

## Data quality and liquidity

Required screening inputs: positive price, nonnegative finite current and average
dollar volume, an existing liquidity score in [0,100], named provider, timestamped
price, and >=10 preceding completed daily sessions. The adapter rejects malformed
OHLCV, duplicate/ambiguous minute timestamps, invalid quotes and prior-session
daily counters. Today's incomplete daily candle and incomplete/future minute
candles are excluded using the existing completed-candle conventions.

Price age must be between 0 and 120 seconds; prior daily history must be no older
than seven days. The minute stage requires >=30 valid bars, >=55% feature coverage,
at least one usable return/VWAP-distance input, 60-second resolution and a latest
completed feature observation no older than 20 minutes. Future or undated data
fails closed. The 20-minute allowance is for explicitly delayed research, not
trade permission. Existing final-decision freshness gates are stricter.

Hard filters, all configurable:

- Price >= $5.
- Preceding completed-session average dollar volume >= $25 million.
- Current dollar volume (latest trade price * current-session shares) >= $1 million.
- Measured spread <= 0.30%; absent/stale spread stays null, is warned about, and
  is not itself a hard rejection. Existing cost/trade gates still require it.

Average dollar volume and LiquidityScore reuse `build_liquidity_observation`
unchanged. The score's point budgets are 35 average dollar volume + 25 spread +
15 trade frequency + 15 volume pace + 5 volatility stability + 5 coverage. The
scanner does not replace its tiering or invent a spread, trade count or volume.

## Transparent, unoptimized ranking formulas

All returns and VWAP distance below are fractions (0.01 = 1%); RSI is 0–100.
`clip(x)` means clamp x to [0,1]. Missing inputs contribute zero; weights are not
renormalized to hide missing evidence.

**Activity** (direction-neutral):

`A = 60*clip((relative_volume - 1)/2) + 40*clip(abs(session_return)/0.04)`

Relative volume reuses the existing elapsed-session volume-rate calculation.
This identifies activity, not a bullish/bearish forecast.

**Fast momentum / dislocation** (existing features only):

`M = 60*clip(abs(return_5m)/0.01) + 20*clip(abs(return_3m)/0.006)
     + 20*clip(abs(relative_strength_market)/0.005)`

`D = 70*clip(abs(distance_from_vwap)/0.02) + 30*clip(abs(RSI14-50)/30)`

`F = max(M, D)`

Momentum >=20 earns `momentum_candidate`; dislocation >=50 with a measured VWAP
distance earns `dislocation_candidate`. Both signs are supported. These tags
mean further research is warranted, not that a fall is a bargain or a reversal
will occur. Activity survivors also receive `unusual_activity`.

**Opportunity ranking** (all component inputs are 0–100):

`O = clamp(0.15*C + 0.25*L + 0.20*A + 0.20*F + 0.10*G + 0.10*Q - P, 0, 100)`

- C: existing calibrated directional confidence, untouched by the scanner.
- L: existing LiquidityScore.
- A, F: activity and fast scores above.
- G: agreement returned by the existing decision contract. Its source is the
  existing mathematical-strategy consensus, NOT independent-model accuracy.
- Q: minimum of screening-field coverage and minute-feature coverage. Screening
  coverage checks price, average/current dollar volume, liquidity score,
  provider, optional spread, relative volume and session return (eight fields).
- P: `10 * opposing_nonzero_returns / available_nonzero_returns`, using existing
  1m/3m/5m returns versus model direction; zero if none are usable.

Weights live in `OPPORTUNITY_WEIGHTS`; thresholds and budgets live in
`ScannerConfig`. No historical optimization or edge claim is made.

**Uncalibrated ranking score — not probability of profit.** Model probabilities
remain separate 0–1 fields. A ranking score of 87 is never reported as an 87%
chance of profit.

## Existing directional pipeline

Finalists use the existing `build_live_prediction` → `predict_probabilities`
(multinomial logistic + boosted-stump average + held-out temperature calibration)
→ `decision_from_prediction` path. No weights, features, label thresholds or
calibration procedure are changed. The scanner never trains or promotes models.

The existing source-specific freshness audit and model-readiness contract remain
authoritative for final trade permission. Delayed features can inform an
explicitly delayed research result while stale feature flags veto a trade. Model
direction/confidence survive `NO_TRADE`. SELL retains the existing bearish/reduce-
existing-long research meaning, not automatic shorting or order execution.

Missing fitted horizons produce structured `unavailable_analyses`, not placeholder
probabilities. Yahoo's one-minute features cannot support `30s`; that horizon is
explicitly unavailable. The existing other horizons can be requested without
changing models, provided a fitted artifact exists.

## Result and diagnostics

Candidates include ticker/company, current snapshot price and separate model
reference price, UP/DOWN/NEUTRAL probabilities, model direction/confidence,
model status/ID/version, raw probabilities/temperature, agreement with its source,
final decision, horizon, opportunity/liquidity/activity/fast scores and audits,
relative/current/average dollar volume, setup tags, reasons and warnings.

Provenance includes snapshot provider/feed, quote/price timestamps, daily and
feature providers, delayed status, freshness ages/ceilings, missing fields,
feature coverage, raw Yahoo minute-start timestamp, canonical completed-close
timestamp, resolution, normalization rule and SPY benchmark timestamp. Missing
or stale benchmark features are not replaced with current market confirmation.

Stage counts expose universe size, page screened, quality/liquidity/activity
survivors, minute-history survivors, fast candidates, inference attempts,
successfully analyzed symbols, model evaluations and returned rows. Capacity
exclusions are separate from threshold/failure exclusions. Up to 100 exclusion
examples and provider error messages are returned. One failed batch/candidate
does not erase unrelated usable results.

No qualifying candidates yields `no_high_quality_candidates` with `candidates: []`.
Thresholds are never relaxed to force output.

## Deterministic fixture output

These are synthetic test observations and mocked probabilities, NOT real stocks,
performance measurements or recommendations. Both pass identical model probabilities;
liquidity and signal evidence produce different ranking scores:

| Ticker | Direction | P_UP / P_DOWN / P_NEUTRAL | Liquidity | Activity | Fast | Opportunity | Final decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| STRONG | UP | .73 / .17 / .10 | 95 | 100 | 100 | 90.7 | NO_TRADE |
| WEAK | UP | .73 / .17 / .10 | 65 | 25 | 40 | 56.2 | NO_TRADE |

The 3,000-symbol budget test screens 1,000, loads minute features for 100,
retains 30 fast candidates, calls the model for 15 and returns 10. It explicitly
reports another 2,000 symbols unscanned (`next_offset=1000`).

## Validation and limitations

61 new scanner/adapter cases plus 15 directly relevant existing cases passed
(76 total). Tests are synthetic/offline. One integration test uses fixed fixture
weights to execute the actual logistic/stump/calibration code without training.
There was no live-provider smoke check, frontend build, full regression suite,
model retraining, scheduling, performance analytics or settlement change.

From the project root:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  backend/tests/test_staged_market_scanner.py \
  backend/tests/test_staged_scanner_adapters.py \
  backend/tests/test_liquidity_engine.py \
  backend/tests/test_predictive_intelligence.py \
  backend/tests/test_predictive_features_models.py::test_historical_features_do_not_change_when_future_rows_are_mutated \
  backend/tests/test_predictive_features_models.py::test_training_targets_are_strictly_after_feature_cutoff_and_do_not_fake_30s

.venv/bin/python -m py_compile \
  backend/app/services/staged_market_scanner.py \
  backend/app/services/staged_scanner_adapters.py \
  backend/tests/test_staged_market_scanner.py \
  backend/tests/test_staged_scanner_adapters.py
```

Main limitations: Yahoo minute features are delayed and the IEX snapshot feed
does not represent consolidated US liquidity. Relative volume compares IEX
current counters with Yahoo daily averages and is labeled a cross-source proxy;
it can understate consolidated activity. Dollar-volume minimums can exclude
otherwise liquid stocks early in a session. A prior Yahoo adjusted close is a
disclosed fallback for session return if the broker's prior daily close is absent.
Universe pages are not automatically rotated. A missing/unvalidated fitted model
does not become trustworthy merely because the scanner ranked its inputs.

The core is consumed by the Task 5A2 continuous service described in
`CONTINUOUS_SCANNER.md`. This one-shot class remains useful for deterministic
calls and tests; it does not itself schedule work, persist model predictions,
or expose alerts. The continuous service adds only lifecycle management,
bounded rotation, current-state persistence, and the read-only state endpoint.
