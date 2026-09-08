# OrionTrader v0.35 prototype reference (historical)

This document describes the previous ten-workspace prototype. It is retained as
an API/feature reference, not as the current UI guide. See the root README for 2.0.

OrionTrader is a local-first market-research and portfolio-intelligence
assistant with a FastAPI backend and React/Vite frontend. It includes guarded
paper-trading tools for testing ideas, while real-money execution stays in the
user's chosen external broker.

## Current capabilities

- Live quotes, stock search, news and candlestick charts through `yfinance`
- Interactive OHLCV charts with crosshair inspection, volume and MA/EMA overlays
- Technical analysis, watchlist, favorites and paper trading
- SQLite-persisted paper account, trade journal, watchlist and Orion memory
- Orion stock analysis, chat, comparison and watchlist ranking
- Portfolio review, trading-journal coaching and portfolio health score
- Daily briefing, opportunity scan and contextual indicator explanations
- Persisted Orion preferences for risk tolerance, time horizon and answer style
- Structured trade theses, invalidation prices and post-trade notes
- Deterministic expectancy, payoff ratio, profit factor and streak statistics
- Streaming Orion chat with user cancellation
- Freshness-aware market-context caching with partial-provider fallback
- Sector and asset-class exposure based on current paper positions
- Daily equity snapshots with drawdown, volatility, return and Sharpe metrics
- Normalized portfolio-versus-benchmark performance charts
- Risk-budget position sizing and simulation-only rebalancing targets
- Deterministic SMA crossover, RSI reversion and breakout backtests
- SQLite-saved strategy configurations and reusable backtest runs
- Local price, RSI, allocation, drawdown and thesis-invalidation alerts
- Freshness-aware earnings, analyst-rating and insider-activity research
- Research Strategy Lab with deterministic trend momentum, trend pullback,
  catalyst/ORB, mean-reversion, volatility-contraction, pairs and long-term
  playbooks
- Confirmed Golden Cross research and defensive Death Cross monitoring with
  explicit rule checklists, levels, blockers and score semantics
- Scrypt-hashed user accounts, secure cookie sessions and CSRF protection
- Separate SQLite databases for every user's portfolio, memory and tooling
- Alpaca paper-account sync with ephemeral credentials and double-gated orders
- Broker-aware Local Simulator / Alpaca Paper / Trading 212 Demo workspace
- Trading 212 Demo portfolio sync and manually confirmed guarded orders
- Selectable Trading 212 Demo/Alpaca opportunity universes with rotating coverage
- Market-wide Alpaca scanner with bounded Orion candidate evaluation
- Shadow, approval and autonomous paper modes with deterministic risk controls
- Backend agent scheduler, persistent proposals, audit trail and kill switch
- Rotating full-universe discovery with transparent lifetime coverage
- Ten-section trading-terminal navigation with persistent operational context
- Day, swing and long-term Orion research boards with evidence and follow-up chat
- Hybrid deterministic/Orion opportunity ranking with auditable score components
- Concrete entry, breakout, stop and target levels from horizon-specific OHLCV
- Entry-ready scans requiring current-zone, trend, volume, liquidity,
  volatility, reward/risk, Orion-review and risk-profile validation
- Honest zero-match results with closest watch setups instead of relaxed gates
- Persistent per-user opportunity-board history across navigation and restarts
- Catalyst Breakout Radar with an auditable 0-100 readiness checklist for
  float, multi-day volume, consolidation, ATR contraction, stock/sector
  strength, recent insider purchases and timestamped catalysts
- Full-broker-universe catalyst discovery with bounded starter-watchlist
  priority, rotating coverage and explicit unavailable-evidence penalties
- Persisted Conservative, Balanced and Aggressive recommendation-risk modes
- Deterministic setup validation and adaptive, currently unlevered risk sizing
- Explosive-Move Move Lab with separate PreMoveScore, IgnitionScore and
  DangerScore, category-specific thresholds and explicit No Trade outcomes
- Normalized Alpaca-news, corporate-action and SEC-filing event evidence with
  reaction latency, freshness, missing-data and source disclosures
- Per-user Move Lab scan history plus an audit-preserving normalized event log
- Explicit Alpaca market/news WebSocket evidence sessions with bounded buffers,
  reconnect health, sequence cursors and snapshot fallback
- Extreme-Mover Replay Lab with cutoff-controlled OHLCV features, separate
  forward outcomes, 20%/50%/100% labels, false positives and missed moves
- Professional Execution Stress Lab with deterministic spread, impact, gap,
  partial-fill, limit no-fill, rejection and LULD-style interruption scenarios
- Protective-stop risk expansion, full formula/limitation audits, per-user
  simulation history and cutoff-safe Replay-to-Execution handoff
- Predictive Intelligence v1 with extensible rolling features, leakage-safe
  multi-horizon labels, calibrated interpretable baselines and regime context
- Cost-adjusted long/short expected value, composite opportunity ranking and
  explicit NO TRADE gates with progressively stricter lower-liquidity rules
- Orion Live Edge plus a per-user Prediction Laboratory for outcome settlement,
  Brier score, calibration, subgroup accuracy and after-cost simulated results
- Chosen-stock Live Edge analysis plus liquidity-first 60-100 symbol discovery
- Fourteen-strategy mathematical consensus and outcome-learning decision memory
- Manual USD-equivalent planning capital for broker-neutral external execution
- Detailed searchable trading glossary, horizon guides and strategy playbooks
- Broker-neutral external execution handoff with no Live credentials or order routes
- Trading 212 Demo cash, positions, history, order tracking and fill journal sync
- Confirmed opportunity deletion and audit-preserving Paper Lab history clearing
- Responsive orbital visual system with reduced-motion accessibility
- Portable Docker Compose deployment, readiness, JSON logs and metrics
- Installable responsive PWA with offline shell and local alert notifications

OrionTrader is for research, decision support and paper trading. It is not
financial advice and does not place live orders.

## Orion Predictive Intelligence v1

Open **Live Edge** after connecting Alpaca Paper research data. First choose
**Build / validate baseline**, then run a bounded scan. This research workflow
does not enable paper or funded orders.

Live Edge now offers two targets:

- **Liquidity-first market** ranks a broad 60-100 symbol discovery batch by
  absolute execution liquidity before analyzing the requested result count.
- **Chosen stock** pins one active tradable US-equity ticker into the evidence
  batch and analyzes only that ticker.

Tier A/B results always appear before Tier C/D. A liquid stock remains visible
in **High-Liquidity Research Watch** even when the correct output is HOLD / NO
TRADE; lower-liquidity NO TRADE rows cannot dominate the board.

The deterministic pipeline now implements all eleven milestone phases:

- LiquidityScore, percentile, evidence coverage and Tier A-D policy gates
- Rolling one-minute features plus genuine quote/sub-minute stream overlays
- UP, DOWN and NEUTRAL labels for one-minute through one-hour horizons
- Multinomial logistic regression plus gradient-boosted decision stumps
- Chronological train/calibration/untouched-holdout blocks and expanding
  walk-forward folds; random splitting is prohibited
- Held-out temperature calibration, execution-cost estimates, long/short EV,
  market regime and composite OrionOpportunityScore
- Explicit `NO TRADE — NO STATISTICAL EDGE` when any reliability, calibration,
  cost, conflict, regime or liquidity gate fails
- A per-user Prediction Laboratory that settles due outcomes and reports
  accuracy, precision, recall, Brier score, calibration, subgroup metrics and
  simulated after-cost results
- Fourteen transparent mathematical strategy families that vote LONG, SHORT,
  NEUTRAL or UNAVAILABLE without changing model probabilities
- A per-user learning brain that remembers settled good/bad decisions, applies
  Bayesian shrinkage, adjusts strategy weights only within bounded limits and
  vetoes sufficiently repeated adverse patterns

One-minute historical bars are never upsampled or mislabeled as thirty-second
evidence, so the `30s` horizon remains unavailable until genuine timestamped
sub-minute outcomes exist. Model probabilities may be shown as experimental,
but a trade remains withheld until the horizon passes every out-of-sample gate.
Laboratory reporting remains explicitly provisional until at least 500 live
predictions have settled.

Outcome memory does not make the model self-certifying. Positive memories
cannot remove a reliability, liquidity, cost, regime or conflict blocker, while
negative memories may add a conservative veto. Clearing prediction history and
clearing learned memory are separate actions.

Orion AI is downstream only. A structured explanation endpoint can discuss the
strongest signals, contradictions, market context and invalidation conditions,
but its schema contains no numeric fields. The backend returns the unchanged
deterministic block with a SHA-256 digest and rejects explanations that attempt
to restate or invent numbers. No predictive endpoint imports an order adapter
or creates an order.

## Run locally

### Windows (recommended)

From the extracted project directory, run:

```powershell
.\start-orion.ps1
```

The launcher creates the Python environment, installs missing dependencies,
creates `backend\.env`, starts both services and opens OrionTrader. On later
runs, use `.\start-orion.ps1 -SkipInstall` for a faster startup. If PowerShell
blocks local scripts, run this once in the current terminal first:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

The launcher reserves ports 8000 and 5173 as one matched backend/frontend pair.
If either port is already occupied, it reports the owning process and stops
before opening the app. Close the old OrionTrader terminal (or stop the reported
PID) and launch again; Vite will never silently switch this launcher to another
port.

For a permanent desktop icon, double-click
`Install-Orion-Desktop-Icon.cmd` once. Windows creates an **OrionTrader**
shortcut on the current user's desktop. Future launches require only that one
shortcut; it starts both services, opens the browser and uses fast startup after
the first dependency installation. The shortcut's execution-policy bypass is
limited to its own PowerShell process and does not change the Windows policy.

For cookie-based login, keep the browser and API on the same hostname. The
launcher opens `http://127.0.0.1:5173`, and manual Vite launches automatically
use an API hostname matching whichever of `localhost` or `127.0.0.1` is in the
browser address bar.

Add `OPENAI_API_KEY` to `backend\.env` to enable Orion AI. The rest of the app
can run without it.

To enable official SEC filing-metadata checks in Move Lab, also set a declared
application identity and monitored contact in `backend\.env`, then restart:

```dotenv
SEC_USER_AGENT=OrionTrader research your-email@example.com
```

This value identifies your client to SEC.gov; it is not an API secret.

Move Lab streaming is operator-started and uses conservative defaults. Optional
server controls are:

```dotenv
ORION_STREAM_MAX_SESSION_MINUTES=240
ORION_ALPACA_STREAM_TRADES=false
ORION_ALPACA_ALL_NEWS_ENABLED=false
```

The first value is capped at 24 hours. Trade-message and wildcard news
subscriptions remain disabled unless deliberately enabled; neither option
connects streaming evidence to an order route.

On the first v0.12 launch, create an account in the browser. The first account
claims an existing `backend/data/orion.db` automatically. Every later account
receives a separate database under `backend/data/users/<user-id>/orion.db`.

### Manual setup (macOS, Linux or Windows)

Backend (from the repository root):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env
# Add OPENAI_API_KEY to backend/.env for Orion AI calls.
cd backend
uvicorn app.main:app --reload
```

The backend still starts without an OpenAI key; only AI endpoints report that
Orion is not configured.

Frontend (in a second terminal):

```bash
cd frontend
npm ci
npm run dev
```

Set `VITE_API_BASE_URL` when the API is not at `http://127.0.0.1:8000`.

## Verify changes

```bash
.venv/bin/python -m pytest backend/tests
cd backend
../.venv/bin/python -m evals.run_quality_evals
cd ../frontend
npm test
npm run build
```

The evaluation fixtures run offline and do not spend API tokens. Market context
is cached for 60 seconds by default; set `MARKET_CONTEXT_TTL_SECONDS` in
`backend/.env` to use a different value from 1 to 3600 seconds.

Runtime data is stored in `backend/data/orion.db`. The database, `.env`, build
output, caches and `node_modules` are intentionally ignored.

Portfolio equity snapshots begin when v0.10 first loads the portfolio and are
upserted once per UTC day. Historical risk and benchmark metrics therefore show
`Collecting data` until enough genuine observations exist; Orion does not
fabricate a pre-upgrade equity curve from incomplete trade data.

Backtests execute signals at the next bar's open and include configurable
commission and slippage assumptions. They are hypothetical, long-only research
tools and never place paper or live orders. Alerts are checked every minute
while the OrionTrader browser page is open; v0.11 does not install an operating
system background service.

The Research workspace evaluates nine deterministic strategy frameworks from
two-year daily history, recent five-minute bars, SPY regime data, current quote
and headlines. A displayed score is required-rule completion, not predicted
win probability. Missing evidence cannot pass. A “Rules matched” label means
only that the latest supplied snapshot met the written checks; it is not an
order instruction. Golden and Death Crosses use 50/200-session simple moving
averages. The Golden Cross still requires market, liquidity and relative-
strength confirmation, while a Death Cross is shown as a defensive warning and
never as an automatic short. Pair analysis is deliberately labeled a
correlation/z-score screen because it does not establish cointegration.

## Alpaca paper broker safety

Orion connects only to `https://paper-api.alpaca.markets`. API credentials stay
in server memory, are isolated by authenticated user, and disappear whenever
the backend restarts. They are never written to SQLite or browser storage.
Order submission is disabled unless the operator sets:

```dotenv
ALPACA_ORDER_SUBMISSION_ENABLED=true
```

Even then, each manual order requires an explicit two-step review and
confirmation in the browser. The review displays symbol, side, quantity, order
type and limit before the request is sent. Live Alpaca endpoints are not
configurable or supported.

## Trading 212 Demo guarded orders

The **Paper Lab** workspace can connect to Trading 212's official Demo API and
display the account summary, open positions, pending orders, recent historical
orders, transactions and dividends. It can also submit manually confirmed
orders to the Demo account. Connecting selects **Trading 212 Demo** as Orion's
active portfolio source, so Overview, Portfolio Intelligence, portfolio
health, reviews, daily briefings and chat use that account context:

- The backend is fixed to `https://demo.trading212.com/api/v0`.
- Reads and writes use separate fixed allow-lists. Writes contain only the
  documented Demo market, limit, stop, stop-limit and numeric-ID cancel routes.
- There is no Trading 212 Live URL, environment selector or funded order route.
- API key and secret are isolated by Orion user in backend process memory. They
  are never saved to SQLite, local storage or `.env`, and disappear on restart
  or Disconnect.
- A short snapshot cache limits accidental repeated requests. Optional history
  failures—including missing optional API permissions—are shown separately
  instead of erasing the usable core account.
- Account totals and profit/loss remain denominated in the Trading 212 account
  currency. When a position response omits its account-currency market value,
  Orion allocates Trading 212's broker-reported invested total proportionally
  and marks the position value as estimated.
- Order value is converted into the account currency with a current FX quote
  before deterministic cash, exposure and daily-limit validation.
- Orion persists review/audit state and broker order IDs, reconciles pending,
  filled, cancelled and rejected states, and imports only reconciled fills into
  the selected user's external Demo journal.

Create a key while signed into the Trading 212 Demo/Practice environment and
grant the account, portfolio, instrument metadata, order and history permissions
needed by the panel. Enter it in OrionTrader's backend-served Paper Lab form.
Do not add it to React source code, commit it to Git or share it in screenshots.

Demo submission is independently server-disabled by default. Review the
safeguards, then set this in `backend/.env` and restart:

```dotenv
TRADING212_DEMO_ORDER_SUBMISSION_ENABLED=true
TRADING212_DEMO_MAX_ORDER_VALUE=1000
TRADING212_DEMO_MAX_POSITION_PERCENT=20
TRADING212_DEMO_MAX_DAILY_ORDERS=5
TRADING212_DEMO_MAX_DAILY_NOTIONAL=2500
TRADING212_DEMO_REVIEW_TTL_SECONDS=300
```

Search and select the exact Trading 212 broker ticker, prepare the order, and
choose **Review Demo order**. The backend resolves instrument metadata,
converts its estimated value into the account currency, checks every limit and
creates a short-lived review. **Confirm Demo order** performs the checks again
and atomically claims the review before submitting it. Cancellation has its own
second confirmation. If a response is interrupted, Orion records
`submission_unknown`, never retries automatically, and attempts only a unique
ticker/side/quantity/price/time match during reconciliation.

Trading 212 never participates in Orion's autonomous agent: there is no AI or
autonomous order method or route. Alpaca Paper remains the only broker used by
Paper Agent automation. Trading 212 instrument metadata can separately supply
the research-only Opportunities universe described below. The [Trading 212 API
documentation](https://docs.trading212.com/) is the source of the
fixed Demo contracts.

## Horizon opportunity research

The **Opportunities** workspace separates Day Trading, Swing Trading and
Long-Term research because evidence that matters for one horizon may be
irrelevant—or dangerous—for another. Choose **Automatic**, **Trading 212 Demo**
or **Alpaca Paper** as the tradable-universe source. Automatic follows the active
connected broker and safely falls back to another connected paper/demo broker.
Deterministic filters reduce that universe before a bounded set receives deeper
market-structure analysis and Orion review.

Each board reports the sampled coverage and returns up to eight ranked research
candidates with a news assessment, confirmation trigger, invalidation and risks.
Use **Ask Orion about this board** to compare candidates or identify missing
evidence. A `STRONG_CANDIDATE` label is not a BUY instruction.

OrionTrader calculates horizon-specific structure directly from OHLCV bars:
15-minute bars for Day, six-month daily bars for Swing and two-year daily bars
for Long Term. Reproducible code measures ATR, trend, momentum, relative volume,
liquidity, volatility, prior support and resistance. When enough data exists it
always returns a concrete entry zone, breakout trigger, protective stop,
research target and reward-to-risk ratio.

The model then critiques that bounded evidence using supplied news, company
profile, analyst and portfolio context. Final rank blends the deterministic
structure score with the model's evidence review and preserves both scores in
the audit. Unsupported model confidence cannot override missing structure.

A plan is classified as **trigger confirmed**, **waiting for breakout**,
**extended—wait for retest**, **below the selected standard**, **sizing
unavailable**, or **insufficient data**. Conditional plans retain their concrete
watch levels instead of collapsing into “plan incomplete.” Only a Strong
Candidate with a confirmed trigger and every risk gate passed receives a
research quantity. The plan never places, approves or transmits an order.

Opportunity discovery does not prioritize owned positions. Alpaca scans combine
live leaders with a rotating slice of its active tradable US equity universe.
Trading 212 scans load the cached Demo instrument directory, preserve the exact
broker ticker, map supported exchanges to independent research symbols, and
screen a rotating batch of 160 instruments. Either path performs deterministic
OHLCV analysis on up to 16 finalists and sends only the strongest eight bounded
evidence sets to Orion for classification as Strong Candidate, Watch or Avoid.

The interface reports the broker directory size, research-mapped assets,
current batch, unsupported mappings, quote failures and cumulative
broker-specific coverage. Full-universe coverage builds across scans; Orion
never sends thousands of symbols to the market-data provider or AI in one
synchronous request. Trading 212 supplies availability metadata only—its Demo
order adapter is not called by an opportunity scan.

The third scan intent, **Catalyst breakout radar**, ranks observable preparation
for a potentially large move. It awards at most 100 deterministic rule points:
small float (20), multi-day volume trend (15), tight consolidation (15), ATR
contraction (10), stock relative strength versus SPY (10), mapped sector
momentum (10), recent insider-purchase records (10), and a timestamped recent
headline or upcoming earnings date (10). Missing or stale evidence earns zero.
The high-potential watch label requires both 80 points and 80% usable evidence.

That readiness score is not a probability, forecast, expected return or buy
instruction. Headline keywords are discovery clues rather than verified facts;
the user must confirm the primary filing or announcement. Current providers do
not supply verified real-time SEC filings, press releases, FDA calendars or
options flow, so those limitations stay visible. A bounded part of a catalyst
scan samples the included starter watchlist while all remaining slots keep
rotating through the selected broker's mapped universe.

## Explosive-Move Move Lab (v0.30 streaming / v0.31 replay / v0.32 execution)

**Move Lab** is a separate research workspace; it does not replace the
horizon-based Opportunities board and has no order endpoint. A bounded rotating
pass starts from the connected Alpaca Paper or Trading 212 Demo tradable
universe, applies liquidity and instrument filters, then audits up to 16
finalists. Repeated passes expand coverage without pretending that one browser
request can deeply analyze every US listing.

Every candidate displays three independent deterministic rule scores:

- **PreMoveScore** measures observable preparation such as volume accumulation,
  volatility and moving-average compression, resistance proximity, relative
  strength, public catalysts and premarket evidence.
- **IgnitionScore** measures current intraday acceleration, VWAP behavior,
  higher lows, opening/prior-high breaks, continuation, spread and event
  recency. It distinguishes preparing, early/confirmed ignition, extended and
  failed-breakout states.
- **DangerScore** measures filing-linked dilution capacity, distress/listing
  events, spread, dollar-volume liquidity and float/squeeze risk.

The scores are rule points, not probabilities, expected returns or instructions.
Liquid large caps, liquid small caps, recent IPOs, biotechnology catalysts,
low-float momentum names and distressed securities use different watch and
danger thresholds. Missing critical evidence cannot pass. Low-float, biotech
and distressed categories require fresh SEC filing metadata; otherwise the
result is **No Trade**.

Alpaca-connected scans can use authenticated REST snapshots for current news
and corporate-action metadata. After a bounded scan, **Start live evidence**
opens one authenticated market-data connection and one news connection for up
to 16 current candidates. The UI exposes connection state, last-data age,
reconnect count, entitlement errors, bounded-buffer drops and an event tape.
New scan finalists update the active subscription. Stopping the stream,
disconnecting Alpaca, signing out, reaching the configured runtime cap, or
shutting down the backend closes it.

Market quotes and bars remain in a bounded memory buffer. Normalized public
news is deduplicated into the selected user's SQLite event audit; credentials
remain in the existing backend-memory-only Alpaca Paper adapter. The scanner
uses fresh streamed observations when present and keeps its REST/snapshot path
as a partial-failure fallback. IEX is the default feed. SIP requires the
appropriate account data entitlement, and provider connection limits still
apply; stream errors are disclosed rather than silently retried forever.

The SEC client reads public
[filing submission metadata](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
only, declares its operator identity, caches responses and limits itself below
the [SEC fair-access ceiling](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
Filing metadata does not prove the contents of a filing or that registered
securities have been sold. See Alpaca's official
[market-data WebSocket](https://docs.alpaca.markets/us/docs/streaming-market-data),
[real-time stock-data](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)
and [historical news](https://docs.alpaca.markets/us/docs/historical-news-data)
documentation for provider contracts and entitlements.

The sibling **Replay Lab** mode tests one ticker over one, two or five years.
For each sampled historical decision close it calculates a separate 100-point
OHLCV preparation checklist using only bars available by that close: volume
accumulation, ATR/range contraction, trend alignment, base/resistance structure
and relative strength versus SPY. It then opens a distinct 10-60 session
outcome window and records whether the subsequent high touched 20%, 50% or
100%, along with the path, drawdown, false positives and missed extreme moves.
Extreme examples are de-duplicated, while the full sampled-decision audit
remains available.

Replay frequencies are descriptive, not probabilities. A chronological 70/30
display helps reveal time decay but does not fit a model or make overlapping
windows independent. The current free provider history is adjusted OHLCV, not
a point-in-time security master: delisted/failed securities, historical news,
filings, float, spreads, halts, LULD events and executable fills are missing,
and vendor back-adjustments can restate older bars. These limitations appear in
every saved replay.

The third **Execution Lab** mode stress-tests a hypothetical market or limit
plan across seven deterministic cases: baseline, wide spread, adverse opening
gap, thin-liquidity/partial fill, LULD-style interruption, broker/venue
rejection and combined stress. It exposes quantity capacity, fill ratio,
average modeled price, spread/impact cost, implementation shortfall and
optional protective-stop risk expansion. Replay examples can hand their
cutoff-safe historical close and preceding 20-session average volume directly
into this separate lab.

The simulator uses explicit assumptions rather than inventing scenario
probabilities. Its LULD-style case blocks immediate execution; it does not
reconstruct official bands, historical NBBO/depth, queue priority, pause tape
or a reopening auction. Official LULD bands use market reference prices and
quote state, and trades cannot occur during a trading pause; see the
[LULD Plan](https://www.luldplan.com/) and
[FINRA LULD guidance](https://www.finra.org/filing-reporting/market-transparency-reporting/trf/luld/faq).
Two-stage alerts, a point-in-time security master, historical microstructure
replay and calibrated probability models remain later phases.

Until those pipelines pass date-split walk-forward validation, all probability
outputs are `null`, borrowed exposure is disabled and adaptive risk remains
research-only. Live streaming, historical replay and execution stress never
enter an order preparation, confirmation or submission path.

## Recommendation risk modes

The Opportunities workspace has three per-user modes:

| Mode | Instrument policy | Risk per setup | Position exposure | Instrument leverage ceiling |
| --- | --- | ---: | ---: | ---: |
| Conservative | Real shares only | 0.35% | 10% | 1x |
| Balanced | Moderate unlevered budget | 0.50% | 15% | 1x |
| Aggressive | Higher unlevered budget | 0.75% | 20% | 1x |

The ceilings are not targets. Borrowed exposure and CFD suggestions are now
disabled in every mode. The modes alter planned account risk, exposure,
quality and reward-to-risk requirements—not leverage. A future leveraged limit
must first pass category-specific replay, realistic execution and walk-forward
validation and remain behind explicit deterministic authorization.

Setup quality is a hybrid research score, not a calibrated probability of
profit. Deterministic OHLCV code owns the price structure and levels; Orion
reviews the broader supplied evidence without receiving the selected risk mode.
The recommendation engine independently validates levels, trigger state,
quality, reward-to-risk, account limits and data quality and owns all sizing and
exposure decisions.

Position quantity is calculated from account risk and stop distance including a
profile-specific slippage allowance, then capped by maximum notional exposure
and available cash. Current plans remain at or below 1x exposure.

Because OrionTrader cannot see an external funded account, users can optionally
save a USD-equivalent planning equity and cash balance. Otherwise Opportunity
plans use the selected Demo/Paper account. Cross-currency sizing uses an
explicit current instrument-to-account FX rate and fails closed when that rate
is unavailable; concrete research levels remain visible. Every saved board records the
profile, sizing-capital source, evidence, validation gates and calculator output
used at creation time.

## Assistant-only execution boundary

OrionTrader deliberately contains no Live broker client, Live credential field,
Live account switch or real-money order route. Alpaca integration is hardcoded
to the Paper endpoint and exists only for validating research and safeguards
without funded capital. Trading 212 integration is separately hardcoded to the
Demo endpoint and permits only manually reviewed and confirmed Demo orders
behind an independent disabled-by-default server flag.

For a real investment, use OrionTrader to research the symbol, record the
thesis, define confirmation and invalidation, and review portfolio impact.
Verify the current quote and order details independently, then place any funded
order yourself in the regulated broker you choose. Record the result in the
journal so Orion can review the process without controlling the account.
CFD availability, broker leverage, margin, spreads, financing, stop behavior,
currency conversion and tax treatment must be verified in the external broker.

## Broker-aware workspace and autonomous paper agent

Connecting Alpaca does not merge it with Orion's local simulator. Use the
**Workspace account** selector in the Alpaca panel to choose either **Local
Simulator** or **Alpaca Paper**. The cash card, positions, portfolio intelligence,
rebalancing simulations and Orion portfolio context follow that selection.
Backtests remain isolated and never submit orders.

After a successful Alpaca connection, OrionTrader now selects **Alpaca Paper**
automatically and the Overview account card shows broker equity, cash, buying
power and invested value. Local Simulator remains available as an explicit
testing workspace; its fixed starting balance is never combined with Alpaca.

The autonomous panel supports four runtime modes:

- **Off** — no scheduled scans.
- **Shadow** — scan and record proposals without submitting orders.
- **Approval** — create proposals that require the exact human approval phrase.
- **Autonomous paper** — submit at most one risk-approved paper limit order per
  cycle, subject to every configured deterministic limit.

Start with Shadow mode. Orion loads Alpaca's active tradable equity universe,
balances most-active, gainer and loser screeners with a rotating slice of that
full universe, and uses IEX snapshots to apply price, volume and spread filters.
Held positions are prioritized for exit review and recently analyzed symbols
are deprioritized. Only the configured finalist count receives deep AI
evaluation, which controls latency and API cost. The Automation panel reports
per-cycle stages and persistent distinct-symbol coverage; it does not imply
that all 13,000+ symbols receive an expensive AI call every cycle.

Autonomous confidence belongs to the selected action. For example, **82% HOLD**
means Orion is strongly confident that waiting is preferable; it is not an 82%
BUY probability. HOLD decisions are stored as neutral observations. The
`risk_rejected` status is used only when Orion proposes BUY or SELL and a
deterministic execution condition blocks the proposed order.

Autonomous submission is disabled by default. It requires both independent
operator flags in `backend/.env`:

```dotenv
ALPACA_ORDER_SUBMISSION_ENABLED=true
ORION_AUTONOMY_ENABLED=true
```

Restart the backend after changing either flag and reconnect the memory-only
Alpaca credentials. Enabling the runtime mode also requires the exact phrase
`ENABLE AUTONOMOUS PAPER`. The agent supports long stock/ETF positions only and
uses day limit orders; no live endpoint, leverage, shorts, options or automatic
liquidation path exists. The risk guardian also rejects execution while Alpaca's
market clock reports the regular session closed.

The **Kill autonomous trading** control stops scheduling and attempts to cancel
only open orders created by Orion's autonomous path. It never liquidates current
positions and never cancels unrelated Alpaca orders. Runtime mode always starts
at Off after a backend restart, while settings, proposals and audit events remain
in the authenticated user's database.

Opportunity boards now have confirmed per-horizon and all-history deletion.
Paper Lab's **Clear visible history** is deliberately different: it requires
the agent to be Off, refuses unresolved approvals and advances a display cutoff.
Proposal and event audit rows remain in SQLite for safety and later review.

## Portable Docker deployment

Create `backend/.env`, then run:

```bash
docker compose up --build
```

Open `http://localhost:8080`. Persistent data uses the `orion_data` volume.
For an internet-facing deployment, terminate TLS at a trusted reverse proxy and
set `ORION_COOKIE_SECURE=true`, `ORION_ALLOW_REGISTRATION=false` after the first
account, and `ORION_ALLOWED_ORIGINS` to the exact HTTPS origin. Back up both
`platform.db` and the complete `users/` directory together.

Operational endpoints are `/health`, `/ready`, and Prometheus-text `/metrics`.
HTTP logs are structured JSON and include request IDs, status and duration but
never request bodies, passwords, cookies or Alpaca keys.

## Mobile PWA

### Use it now on the same Wi-Fi

The Windows launcher intentionally binds to the PC only. For phone access, use
the Docker deployment instead:

1. Connect the PC and phone to the same trusted Wi-Fi network.
2. In the project folder run `docker compose up --build`.
3. Run `ipconfig` on Windows and find the PC's **IPv4 Address** (for example,
   `192.168.1.25`).
4. On the phone open `http://192.168.1.25:8080`, replacing the example with
   the actual address. Allow Docker/port 8080 on the Windows **Private network**
   firewall prompt if asked.

Keep the PC awake and Docker running. Do not expose port 8080 through router
port forwarding. The HTTP LAN address works as a responsive mobile web app, but
mobile browsers generally require HTTPS before they enable service-worker PWA
installation, offline shell behavior and notifications.

### Install it as a full PWA

Deploy the portable Docker stack behind a trusted HTTPS reverse proxy, then set
`ORION_COOKIE_SECURE=true`, configure `ORION_ALLOWED_ORIGINS` to the exact HTTPS
origin, and disable open registration after creating the account. Visit that
HTTPS address on the phone and choose **Install app** / **Add to Home Screen**
from the browser menu. The PWA caches only the application shell; authenticated
API and market responses remain network-only, and notifications still require
explicit permission.

See [Roadmap.md](Roadmap.md), [Project_Handoff.md](Project_Handoff.md), and
[AUDIT_REPORT.md](AUDIT_REPORT.md) for current engineering status.
