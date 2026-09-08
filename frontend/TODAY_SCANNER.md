# TODAY scanner surface — OrionTrader 3.0

## Market-intelligence checkpoint

Nine compact selectors: Orion Picks, Biggest Gainers, Biggest Losers, Most Active,
Unusual Volume, Momentum Leaders, Potential Bargains, Buy Pressure, Sell Pressure.
Orion Picks preserves existing cards. Intelligence cards show ticker, price,
category metric, session return, liquidity, freshness, source/time and reason
when supplied. Clicking a ticker invokes the existing Analyze workflow.

TODAY also reads `GET /scanner/market-intelligence`. Both authenticated endpoints
are polled independently every 15 seconds while visible. Selecting a category
makes no request. No scans, training or downloads are triggered. Hung reads time
out after 15 seconds; requests never overlap for an endpoint. Cleanup cancels
reads and timers. Connection changes reset caches. A failure in one endpoint
does not discard the other's successful response.

Failed-refresh cached results are STALE, not current. Intelligence timestamps
also age locally against backend-supplied freshness ceilings without network
work. Stale observations are collapsed under last-known results. Missing values
are unavailable, not zero. CURRENT / DELAYED / STALE and partial coverage remain
explicit, with rotation progress and last broad-scan time where known.

Most Active is market activity, not Most Bought. Both pressure lists display
**Inferred Quote Pressure**, not executed buying or selling. Potential Bargains
requires ATR- and return-volatility-normalized VWAP dislocation plus oversold RSI
and reversal confirmation; its metric is ATR distance, not a probability.
Exact formulas are in `backend/MARKET_INTELLIGENCE.md`. These research thresholds
are not statistically validated trade recommendations. Technical categories
still cover activity finalists and use delayed minute evidence.

The TODAY workspace reads the authenticated, read-only `GET /scanner/current`
endpoint. It does not call `/core/today`, start a model job, train a baseline,
or trigger a market scan. `ScannerScheduler` remains responsible for market
work on the backend.

## Refresh behavior

`TodayView` performs one state read when mounted and polls every 15 seconds
while the browser tab is visible. An `AbortController` cancels an in-flight
read on unmount or at its timeout. Polling is cheap and only reads the
persisted current snapshot. A scanner state change therefore updates the cards
without a page reload or a second scanner loop.

## States shown

The page distinguishes `SCANNING`, `CURRENT`, `DELAYED DATA`, `STALE`,
`MARKET DATA UNAVAILABLE`, `NO HIGH-QUALITY CANDIDATES`, and `PARTIAL UPDATE`.
Recovered/old candidates appear only under **Last known candidates · clearly
stale**. Missing state shows an explicit first-scan message; no synthetic
stocks or probabilities are inserted.

## Candidate cards

Cards show ticker/company, direction, directional confidence, Opportunity Score
(`score / 100`, never a probability), Liquidity (`score / 100`), current price,
RVOL, expected horizon, setup tags, concise reasons, freshness, and final
decision. `NO TRADE` remains visible and is explicitly described as distinct
from an interesting opportunity. The Analyze action routes through the existing
`CoreApp` selection/navigation path; Save stock uses the existing watchlist API.

## Progress and limitations

Universe progress is displayed only when the backend supplies a valid total;
unknown totals remain `Unavailable`. Active-candidate count, current page,
page count, and last broad scan time come directly from scanner state. Delayed
Yahoo features retain their delayed label and are never presented as current.

The UI intentionally does not add alerts, new model indicators,
model training, probability changes, settlement, or order execution.
