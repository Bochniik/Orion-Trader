# Market intelligence — OrionTrader 3.0

`GET /scanner/market-intelligence` returns eight category objects, coverage,
timestamps, feed provenance, scanner failure state and limitations. It uses the
existing authenticated user scope and is read-only: no scan, provider request,
model call or training is triggered by a GET.

## Data flow and storage

The staged scanner exports compact liquidity-qualified screening observations
before its activity cutoff. It also attaches an eight-value technical summary and historical feature close for
activity finalists that pass the existing minute-data quality gate. These are
existing calculations, not another dataset/download or model invocation.

The continuous scanner merges observations by ticker into its existing SQLite
current-state JSON (`market_intelligence`). No database reset or table migration
is required. Older state documents start with an empty category pool.

One summary per symbol is retained for the current New York exchange date,
bounded at 10,000 symbols. Keeping runner-ups permits correct Top-10 promotion
when a previous leader falls in rank. Duplicate refreshes replace a ticker,
not an entire page. Explicitly rejected re-screenings remove that ticker;
missing symbols in partial provider failures retain only their original data.
Out-of-order older observations cannot overwrite newer ones. Universe changes
remove departed names. Capacity evictions, if any, are disclosed in coverage.
This is bounded current-session state, not a historical observations database.

## Formulas (returns are fractions)

| Category | Admission and ranking |
| --- | --- |
| Biggest Gainers | Latest trade / previous close - 1 > 0; descending percentage return |
| Biggest Losers | Same return < 0; most negative first |
| Most Active | Latest price × current-session share volume, descending |
| Unusual Volume | Existing elapsed-session current volume rate / historical average rate > 1, descending |
| Momentum Leaders | Positive 1m, 3m and 5m returns; existing momentum score >= existing fast threshold |
| Potential Bargains | RSI in [0,35], 1m return > 0, 5m return < 0; at least 1.5 ATR and 2 return-volatility units below VWAP; rank by ATR dislocation |
| Buy Pressure | Valid timestamped displayed bid/ask sizes; imbalance > 0.12 |
| Sell Pressure | Same evidence; imbalance < -0.12 |

Momentum score:
`60*clip(abs(r5)/.01) + 20*clip(abs(r3)/.006) + 20*clip(abs(relative_strength_market)/.005)`.
Missing relative strength contributes zero, as in the existing fast-score rule.

Mean-reversion dislocation uses the historical feature close P, existing VWAP
return-distance d, ATR14 A (price units), and realized volatility V (sample
standard deviation of 20 one-minute returns):

- VWAP = P / (1+d), with -1 < d < 0.
- ATR dislocation = (VWAP-P)/A, required >= 1.5.
- Return-volatility dislocation = -d/V, required >= 2.
- RSI must be in [0,35], 1m return positive, and 5m return negative.
- P, A and V must be finite and positive; missing/invalid inputs exclude.

Both normalization gates are required after existing liquidity, session and
feature-quality checks. The newer live trade price never substitutes for the
historical feature close. `mean_reversion_evidence` retains a numeric audit.
Older cached summaries missing these statistics remain excluded until a normal
scanner refresh collects them. No new download or model feature is introduced.
These are descriptive thresholds, not a calibrated z-score, significance test,
validated edge, fair-value estimate or BUY recommendation. No tuning was done.

Quote imbalance: `(bid_size - ask_size)/(bid_size + ask_size)`. Both sizes and
prices must be finite and positive, ask > bid, and spread must pass the existing
ceiling. Quote timestamp is validated separately from trade timestamp. The API
labels both lists **inferred quote pressure**, never executed buying/selling.

All categories first pass the existing scanner's data quality and liquidity
filters: price >= $5, average dollar volume >= $25M, current dollar volume >=
$1M, >=10 completed daily sessions and spread <=0.30% if measured. Missing
spread remains missing under the existing rule; pressure additionally requires
a valid measured quote. Ties use liquidity score then ticker for stable order.

## Freshness and cross-page meaning

Each category has `items` (Top-10 currently usable current/delayed observations)
and `last_known` (Top-10 stale/unavailable observations, clearly separated).
Rankings cover retained scanned observations, not simultaneous full-market data.

Freshness is recalculated at read time from original source timestamps. Price
and pressure quotes use the unchanged 120-second limit. Technical evidence uses
the existing 120-second ideal and 1,200-second maximum; known Yahoo delay stays
explicit even when its age is within the ideal limit. Future/missing times are
unavailable. A 600-second new broad page does not renew older pages' timestamps:
they remain retained but move into `last_known`. No model probabilities or trade
decisions are added to these descriptive rankings.

Restart recovery, disconnected/disabled scanners and scanner failures make
retained evidence stale until the scanner resumes. Prior-session data is not
included in today's categories. Reads do not mutate stored observations.

## Limitations

- Universe comes from connected Alpaca active/tradable assets, not a certified
  complete US market. Page coverage and capacity limits remain visible.
- IEX snapshots are not consolidated US activity. Most Active means market
  activity, NOT Most Bought; no ownership or signed trade-flow data is present.
- Relative volume compares IEX counters with Yahoo prior daily averages, an
  explicitly cross-source proxy. Prior-close Yahoo fallback is disclosed.
- Momentum/reversion cover activity finalists only; they do not cause extra
  minute-history downloads. Yahoo features remain delayed.
- Displayed quote sizes can change/cancel and may be misleading. They do not
  establish aggressor-side trade pressure or predict future returns.
- No model, calibration, settlement, provider or order changes. TODAY now exposes
  the categories; see `frontend/TODAY_SCANNER.md`.

## Targeted validation

Tests exercise all category formulas, liquidity rejection, negative/flat
mean-reversion exclusions, invalid/stale quote evidence, source timestamp
boundaries, Top-N runner-up promotion, cross-page and active-refresh merging,
session rollover/capacity, restart/user isolation, read-only API behavior,
unchanged provider/model call budgets and preservation of stored timestamps.
