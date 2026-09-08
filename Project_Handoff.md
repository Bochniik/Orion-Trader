# OrionTrader project handoff

## Current release: OrionTrader 2.4 — Milestone 4 (2.4.0)

Release naming now uses `OrionTrader-2.4.zip`; future upgrades increment the second number (`2.5`, `2.6`, …).

Read `docs/MILESTONE_2.md` first. Analyze and explicit Today Refresh now run
bounded cancellable background jobs, automatically prepare a baseline when
needed, enforce purged cross-symbol validation and source-specific freshness,
and persist final decisions including WAIT. My Stocks has saved-plan checks,
opt-in foreground one-minute monitoring and recent decision history. Existing
watchlists, positions, auth, charts and predictive services remain intact.

Limits: one backend process, two worker slots, one active job/user, five-minute
publication deadline, six-hour preparation cooldown, no automatic retry loop,
four A/B training symbols from an 80-symbol sample. No true historical quote
tape, executed fills, push notifications or unattended monitoring. Older models
must be revalidated; failed candidates never replace the incumbent. Browser QA
remains unavailable without Chromium. See CHECK_REPORT for actual checks.

Next: Milestone 3 — Decision quality and measured outcomes, not another lab tab.
The older handoff sections below are historical; no new Git repository was made.

## Previous release: OrionTrader 2.0 — Milestone 1

The primary UI is now Today / Analyze / My Stocks. Today is the default and
returns at most five distinct high-liquidity setups when prerequisites pass.
Analyze is a one-input facade over existing evidence, with WAIT and unavailable
states instead of manual baseline controls. My Stocks preserves saved watchlist,
positions and journals, and displays checked alert exceptions without claiming
automatic monitoring. Data connections are secondary, with no order controls.

Read `docs/ORIONTRADER_2_ARCHITECTURE.md` before the next change. It supersedes
the old ten-panel product direction. The new files are `frontend/src/core/*`,
`backend/app/api/core_routes.py` and `backend/app/services/decision_engine.py`.
No data was deleted. Existing routes/stores/tests are retained. The complete
browser smoke script is included but unverified here because Chromium download
was unavailable. Do not call this release visually browser-verified.

The next milestone is One-action decision orchestration, not another lab tab.

## Current branch state

This exported workspace has no embedded `.git` directory, so a branch could not
be created inside the archive. Integrate this milestone on a dedicated
`feature/orion-2-core-experience` branch in the canonical repository before
committing. Do not initialize a replacement repository merely to manufacture
branch metadata.

## Architecture

- `backend/app/api/routes.py` — HTTP contracts and portfolio snapshot/health logic
- `backend/app/services/orion_ai_service.py` — OpenAI Responses API prompts
- `backend/app/services/memory_store.py` — ticker conversations and preferences
- `backend/app/services/paper_trader.py` — paper account, positions and journal
- `backend/app/services/context_cache.py` — freshness-aware market context cache
- `backend/app/services/portfolio_intelligence.py` — exposure, risk and simulators
- `backend/app/services/backtesting.py` — deterministic strategy simulation
- `backend/app/services/strategy_intelligence.py` — deterministic live-snapshot strategy rules and levels
- `backend/app/services/strategy_store.py` — saved strategies and alerts
- `backend/app/services/auth_store.py` — accounts, password hashes and sessions
- `backend/app/services/alpaca_broker.py` — memory-only Alpaca paper connection
- `backend/app/services/trading212_demo.py` — fixed-host Demo read/order adapter
- `backend/app/services/trading212_execution.py` — review, limits, confirmation and reconciliation
- `backend/app/services/autonomy_store.py` — workspace source, risk settings, proposals and audit
- `backend/app/services/autonomous_agent.py` — scanner, risk guardian and scheduler
- `backend/app/services/recommendation_engine.py` — deterministic profile, sizing and instrument gates
- `backend/app/services/opportunity_intelligence.py` — horizon-specific OHLCV scoring, levels and hybrid ranking
- `backend/app/services/catalyst_engine.py` — evidence-aware breakout-readiness scoring and disclosures
- `backend/app/services/explosive_move_engine.py` — separate preparation, ignition, danger and category gates
- `backend/app/services/adaptive_risk.py` — unlevered exposure/stop/slippage/gap-risk limits
- `backend/app/services/sec_edgar.py` — declared-identity cached SEC submissions metadata
- `backend/app/services/explosive_move_store.py` — per-user scan and event-audit persistence
- `backend/app/services/alpaca_stream.py` — bounded Alpaca market/news WebSocket sessions and observability
- `backend/app/services/extreme_move_replay.py` — cutoff-controlled OHLCV replay and outcome audits
- `backend/app/services/execution_simulator.py` — deterministic fill, cost, gap, pause and rejection stress
- `backend/app/services/liquidity_engine.py` — deterministic Phase 1 metrics, score, tiers and universe rotation
- `backend/app/services/predictive_features.py` — leakage-safe historical and real-time rolling feature contracts
- `backend/app/services/predictive_models.py` — calibrated interpretable baselines and walk-forward evaluation
- `backend/app/services/predictive_intelligence.py` — regime, EV, composite score and NO TRADE orchestration
- `backend/app/services/predictive_strategy_ensemble.py` — fourteen deterministic strategy families and consensus
- `backend/app/services/predictive_store.py` — per-user liquidity, model, prediction, outcome and learning-memory persistence
- `docker-compose.yml` — portable frontend/backend deployment and data volume
- `Start-OrionTrader.cmd` — dependency-aware double-click Windows launcher
- `install-orion-shortcut.ps1` — per-user desktop shortcut creation
- `backend/evals/` — offline Orion quality fixtures and runner
- `backend/app/services/watchlist.py` — persistent ordered watchlist
- `frontend/src/api/api.js` — all backend calls
- `frontend/src/components/OrionAiPanel.jsx` — Orion analysis, memory and AI tools
- `frontend/src/main.jsx` — dashboard orchestration and selected ticker state
- `frontend/src/navigation.js` — workspace definitions and deep-link validation
- `frontend/src/components/WorkspaceNav.jsx` — desktop/sidebar and mobile/tab navigation
- `frontend/src/components/CandleChart.jsx` — OHLCV chart, overlays and crosshair detail
- `frontend/src/components/StrategyResearchPanel.jsx` — selectable Research Strategy Lab and pair screen
- `frontend/src/components/LearningCenterPanel.jsx` — glossary and strategy playbooks
- `frontend/src/components/OpportunityBoardPanel.jsx` — horizon scans and board assistant
- `frontend/src/components/ExplosiveMovePanel.jsx` — Move Lab scan, score, risk and history UI
- `frontend/src/components/ExtremeMoveReplayPanel.jsx` — historical replay, paths, misses and holdout UI
- `frontend/src/components/ExecutionSimulationPanel.jsx` — scenario matrix, stop stress and saved audits
- `frontend/src/components/MoveLabWorkspace.jsx` — Live Scanner / Replay / Execution Lab workflow
- `frontend/src/components/PredictiveIntelligencePanel.jsx` — Live Edge and Prediction Laboratory workspace
- `frontend/src/components/RiskProfilePanel.jsx` — persisted profile and planning-capital controls
- `frontend/src/components/TradeRecommendation.jsx` — audited risk-plan presentation
- `frontend/src/components/AssistantHero.jsx` — assistant-first Overview narrative and actions
- `frontend/src/components/ExecutionBoundaryPanel.jsx` — external funded-execution handoff
- `frontend/src/components/Trading212DemoPanel.jsx` — portfolio, order review and reconciliation panel
- `frontend/src/uiPresentation.js` — testable product-boundary presentation contract

SQLite data lives in `backend/data/orion.db`. Memory, watchlist and paper trading
use separate tables in the same WAL-mode database.

## v0.35 patch

- Added chosen-stock Live Edge analysis with pinned ticker inclusion.
- Expanded automatic discovery to 60-100 candidates and made absolute
  LiquidityScore the first sorting key inside every board section.
- Added a Tier A/B research-watch section and demoted lower-liquidity NO TRADE
  observations to a collapsed audit.
- Added fourteen deterministic mathematical strategy families with transparent
  votes, formulas, missing-data states and weighted consensus.
- Added durable per-user good/bad outcome memory, Bayesian-shrunk performance
  profiles, bounded learned strategy weights and adverse-pattern vetoes.
- Kept probabilities immutable and preserved every model, cost, liquidity,
  calibration, regime and assistant-only boundary.
- Regression baseline is 228 backend tests and 54 frontend tests.

## v0.34 patch

- Completed Orion Predictive Intelligence phases 2-11 with a deterministic,
  assistant-only architecture and explicit order-path separation.
- Added rolling historical/stream features, leakage-controlled multi-horizon
  outcomes and calibrated logistic/boosted-stump baselines.
- Added execution-cost-aware EV, market regime, composite opportunity scoring,
  progressive liquidity gates and exact NO TRADE behavior.
- Added the Live Edge workspace and a per-user outcome laboratory with Brier,
  calibration, subgroup and simulated after-cost reporting.
- Preserved thirty-second honesty: one-minute history cannot create a 30-second
  model. All unvalidated horizons fail closed.
- Added qualitative-only Orion explanation of immutable deterministic evidence,
  guarded by schema validation and a SHA-256 evidence digest.
- Regression baseline is 222 backend tests and 54 frontend tests.

## v0.33 patch

- Added Predictive Intelligence Phase 1 as a backend-first liquidity gate.
  Average/current dollar volume, time-adjusted relative volume, bid/ask spread,
  trade frequency, volume rates and daily realized volatility are calculated
  deterministically and retained with evidence provenance.
- LiquidityScore is an auditable 100-point execution-quality rubric and never a
  directional confidence value. Results are separated into Tier A-D and sorted
  with Tier A first.
- Future model gates become progressively stricter for Tier B-D, but are
  labeled policy thresholds only. No model, expected value or probability is
  active in this release.
- The sampler caps each synchronous pass at 100 securities, prioritizes live
  Alpaca activity for roughly 70% of the batch and rotates the remainder through
  the active tradable US-equity universe per user.
- Current incomplete daily rows are excluded from preceding-session averages.
  History-dependent score points require at least ten completed sessions, and
  absent feed fields remain null with zero points.
- Added source/coverage/partial-failure disclosures, including the limitation
  that IEX snapshots may understate consolidated volume and trade frequency.
- Added authenticated status/ranking endpoints and per-user compact/full SQLite
  history contracts. Frontend API bindings are ready for the later Live Edge UI.
- Structural tests prove the ranking route contains no LLM or submission call.
- Regression baseline is 210 backend tests and 52 frontend tests.

## v0.32 patch

- Added a professional Execution Lab as a third Move Lab mode. It stress-tests
  a hypothetical stock plan without importing broker services, credentials or
  any submission route.
- The deterministic matrix includes baseline, wide-spread, adverse-gap, thin-
  liquidity/partial-fill, LULD-style interruption, rejection and combined-
  stress cases. No scenario probability is estimated.
- Market and limit plans use side-aware half-spread cost, explicit base
  slippage, square-root participation impact, scenario volume capacity and
  auditable limit-price quantity solving.
- Stops show modeled gap/slippage risk expansion. Pauses, rejections and limit
  no-fills never receive a misleading zero execution cost.
- Official LULD bands, NBBO/depth, queue priority, venue tape, historical halt
  events and reopening auctions are explicitly unavailable. The configurable
  interruption scenario blocks immediate fills rather than inventing them.
- Simulation histories are isolated per user in SQLite and load summaries
  before full scenario audits. They can be cleared without altering Move Lab
  scans, public-event evidence or Replay Lab history.
- Replay examples now record the cutoff-safe preceding 20-session average
  volume and can hand the historical close/volume directly to Execution Lab.
- Regression baseline is 195 backend tests and 51 frontend tests.

## v0.31 patch

- Added an Extreme-Mover Replay Lab as a sibling mode rather than mixing
  historical results into the live scanner. One/two/five-year history,
  forward-window, five-to-20-session stride and flag-score controls are bounded
  by the API.
- Every factor is computed from bars ending at the displayed decision close.
  The subsequent 20%/50%/100% outcome, peak, low and close-return path is held
  in a separate window and never feeds the score.
- The replay score is explicitly distinct from live PreMoveScore: current
  company profiles, float, news, filings and fundamentals are excluded because
  the current providers cannot reproduce those fields point in time.
- Added score-band counts, chronological 70/30 descriptive segments,
  non-overlapping extreme examples, false positives, missed moves and complete
  sampled-decision audits. No frequency is labeled a probability.
- Added per-user SQLite replay history with compact list queries and full-detail
  restoration. Clearing replay history does not alter Move Lab scans or the
  normalized public-event audit.
- Made `auto_adjust=True` explicit for daily history. The UI and response still
  disclose survivorship, delisting, vendor-restatement, overlap, historical
  event, spread, halt and execution-data limits.
- Replay Lab has no import or reference to any order adapter. Borrowed exposure
  remains disabled and all outputs remain research-only.
- Regression baseline is 182 backend tests and 49 frontend tests.

## v0.30 patch

- Added a per-user stream manager that opens at most one Alpaca market-data and
  one news WebSocket for an explicitly selected, bounded symbol set. Market
  wildcards are never used; all-news requires a separate disabled-by-default
  server policy.
- Added authentication, feed selection, channel state, freshness ages,
  reconnect/backoff, fatal entitlement handling, sequence cursors, drop counts
  and maximum-runtime controls. Errors and public event payloads never expose
  the memory-only Alpaca credentials.
- Quotes, optional trades and bars stay in bounded process memory. Deduplicated
  Alpaca public news is normalized into each user's existing event-audit table.
- Added explicit start/update/stop/status/event HTTP contracts plus stream
  telemetry in `/metrics`. Active scans overlay only fresh stream observations
  and retain the previous snapshot route as fallback.
- Added Move Lab operator controls, channel health, live evidence tape and
  candidate evidence badges. The stream stops on Alpaca disconnect, logout,
  application shutdown or the configured runtime ceiling.
- The data path remains research/shadow-only and has no reference to an order
  service or route. Probability fields stay blank and all risk profiles remain
  unlevered.
- Regression baseline is 175 backend tests and 46 frontend tests.

## v0.29 patch

- Added a new Move Lab rather than overloading the existing Opportunities
  workflow. It scans a bounded rotating slice of a connected broker universe
  and preserves each result in the selected user's SQLite database.
- Added independent PreMoveScore, IgnitionScore and DangerScore structures with
  factor/risk points, source explanations, evidence coverage and explicit
  unavailable-data handling. No combined buy score exists.
- Added category-specific watch/danger thresholds and exposure caps. Low-float,
  biotech and distressed categories fail closed without fresh SEC metadata.
- Added normalized Alpaca REST news and corporate-action snapshots plus a
  declared-identity SEC submissions client. SEC records are metadata-only and
  do not imply filing contents or an active sale.
- Added Adaptive Risk v1. It derives a realistic ATR/category stop, sizes from
  planned dollar loss, applies the most restrictive exposure/cash cap, reduces
  risk during drawdown/concentration and estimates slippage and gap loss.
- Disabled all borrowed-exposure suggestions, including the previous optional
  CFD paths. The old response keys remain for backward compatibility, but caps
  are 1x and the calculator version is `recommendation-v3-unlevered`.
- Probability targets remain `null` with `not_calibrated` status. Persistent
  WebSockets, execution replay, alerts and ML deployment are later phases.
- Regression baseline is 162 backend tests and 45 frontend tests.

## v0.28 patch

- Added the Catalyst Breakout Radar as a third saved Opportunities scan intent.
- Added a deterministic eight-factor 100-point readiness model with explicit
  evidence coverage; high-potential requires score and coverage of at least 80.
- Added fresh daily OHLCV/SPY/sector calculations, normalized float and
  short-interest context, seven-day catalyst headlines, upcoming earnings and
  180-day insider-purchase evidence. Missing/stale fields earn no points.
- Catalyst starter symbols reserve only a bounded portion of each scan. The
  remaining batch and finalist slots retain rotating broker-universe discovery.
- Orion receives the readiness audit as critique context, but the prompt labels
  it rule points rather than probability. Market structure, entry readiness and
  risk-plan validation remain independent and authoritative.
- Added an expandable score-factor and microstructure audit to current/saved
  opportunity cards, with explicit absent SEC/press/FDA/options-feed limits.
- Regression baseline is 152 backend tests and 43 frontend tests.

## v0.27 patch

- Added nine Research strategy playbooks with deterministic rule-completion,
  status, evidence, entry/invalidation/target planning and fail-closed missing
  data behavior.
- Added 50/200-session Golden Cross confirmation and defensive Death Cross
  monitoring. Neither crossover is presented as a complete order decision.
- Added catalyst/ORB, RSI(2) mean reversion, volatility contraction, market
  regime, relative strength, liquidity and volume checks using cached daily,
  intraday, quote, headline and SPY inputs.
- Added an optional peer-ticker correlation/z-score divergence screen with
  explicit absent-cointegration disclosure.
- Research now has a horizontally selectable Strategy Lab with direct Orion and
  backtest handoffs. Unaligned strategies expose no actionable price levels.
- Regression baseline is 145 backend tests and 43 frontend tests.

## v0.26 patch

- Added All quality setups / Entry-ready now scan intent to Opportunities and
  persists the choice in per-user board history.
- Added a market-structure-v2 readiness audit for current quote inside entry
  zone, technical quality, trend, liquidity, volatility, reward-to-risk,
  breakout, relative volume and chase distance.
- Entry-ready is a three-stage result: deterministic technical readiness,
  Orion evidence review and the selected risk-profile plan must all pass.
- Highest-ranked setup presentation is rebuilt after the risk plan, so a later
  rejection cannot remain labeled actionable.
- No-match scans retain the closest research candidates and explicitly state
  that none passed every gate.

## v0.25 patch

- Added deterministic market-structure analysis using 15-minute Day, six-month
  daily Swing and two-year daily Long-Term bars.
- Added auditable component scores for trend, momentum, volume, liquidity,
  volatility and breakout structure plus concrete entry zone, breakout, stop,
  target, support, resistance, ATR and reward-to-risk values.
- Opportunities now screen 160 rotating broker instruments, calculate structure
  for up to 16 finalists and send only the strongest eight evidence sets to
  Orion for bounded news/profile/portfolio review.
- Final order is a calibrated hybrid of deterministic and model evidence.
  Missing structure caps the result instead of allowing unsupported AI
  confidence to create a Strong Candidate.
- Replaced generic incomplete plans with explicit confirmed, awaiting-breakout,
  extended/retest, below-standard, sizing-unavailable and data-insufficient
  states. Conditional setups keep their concrete watch levels.
- Recommendation sizing now uses explicit instrument-to-account FX rates.
  Optional news/profile gaps no longer invalidate complete critical OHLCV data.
- Opportunity boards expose the highest-ranked setup, both score sources, full
  level plan and decision audit. Execution remains external.

## v0.24 patch

- Opportunities can resolve its universe from Automatic, Trading 212 Demo or
  Alpaca Paper without coupling research discovery to autonomous execution.
- Trading 212 instrument metadata is cached, normalized into exact broker
  tickers plus independent market-data aliases and rotated in bounded
  100-instrument batches. Up to eight finalists reach Orion.
- Saved boards carry the source, provider/mapped universe counts, unsupported
  mappings, quote gaps, exact broker ticker and per-broker cumulative coverage.
- Recent-candidate deprioritization and coverage are scoped by broker in each
  user's SQLite database.
- Cross-currency risk quantities fail closed without explicit FX conversion;
  research ratings remain available.

## v0.23 patch

- Added a fixed-host Trading 212 Demo execution adapter for documented market,
  limit, stop and stop-limit orders plus numeric-ID cancellation. There is no
  Live host, environment switch or autonomous submission method.
- Added exact instrument-directory selection, current account-currency FX
  conversion, deterministic order-value/cash/concentration/daily limits,
  duplicate protection and a short-lived review.
- Confirmation revalidates every input and uses an atomic SQLite state
  transition to prevent concurrent double submission. Network/ambiguous results
  become `submission_unknown` and are never retried automatically.
- Added broker-state reconciliation, partial/filled/cancelled/rejected status
  tracking, unique recovery of recent unknown submissions, confirmed
  cancellation and idempotent external Demo fill-journal synchronization.
- Added the full Paper Lab workflow, tracked-order status, review gates and
  visible Demo/manual/no-Live/no-autonomy boundaries.
- Trading 212 credentials remain per-user and memory-only. Review, audit,
  broker IDs and reconciled journal rows persist in the user's SQLite database.

## v0.22 patch

- Trading 212 Demo is now a third active workspace source. Its normalized,
  account-currency portfolio contract feeds Overview, Portfolio Intelligence
  and every Orion endpoint that already consumes the active portfolio.
- Connecting selects Trading 212 Demo; disconnecting or a backend restart
  safely falls back to Local Simulator. Workspace status exposes both broker
  connections without merging their ledgers.
- Position values prefer direct broker values. Where Trading 212 omits them,
  the adapter distributes its account-level invested value across positions
  using quote-relative weights and marks those values as estimates.
- At v0.22 Trading 212 remained fixed-host GET-only. v0.23 adds separately
  guarded manual Demo execution while keeping it absent from the autonomous
  manager and risk guardian; Alpaca Paper remains the sole automated-paper
  execution adapter.
- Optional 403 permissions now have explicit metadata and UI language instead
  of appearing as a failed core connection.

## v0.21 patch

- Added an official Trading 212 Demo adapter whose base URL and endpoint
  allow-list are constants. Authentication is HTTP Basic with per-user
  memory-only key/secret pairs; the adapter exposes no method for POST, DELETE
  or a Live host.
- The Demo overview aggregates account summary, positions, pending orders,
  historical orders, transactions and dividends. Account validation fails
  closed; optional feed failures return partial data with named errors.
- Paper Lab originally displayed the mirror without promoting it to Orion's
  active portfolio source; v0.22 adds the reviewed read-only normalization.
  Journal import and Trading 212 order transmission remain absent.
- Opportunities can permanently delete saved boards by horizon or all at once.
  Paper Lab only clears visibility: `history_visibility` stores max proposal and
  event IDs while retaining all audit rows.

## v0.8 patch

- Fixed SQLite memory visibility, restore, clear and preference persistence.
- Made the API boot without an OpenAI key and return 503 only for AI actions.
- Enforced structured stock-analysis output with a Pydantic response model.
- Fixed frontend/backend Orion endpoint and request-body mismatches.
- Fixed duplicate watchlist-removal logic and favorites removal wiring.
- Separated the search input from the active ticker to stop API calls on every
  partially typed symbol.
- Added daily briefing, opportunity scan, journal review, health explanation and
  indicator-explanation controls.
- Persisted watchlist state and fixed full-history realized P&L aggregation.
- Added backend unit/API tests and frontend API contract tests.

## Orion AI v1.1 patch

- Structured theses, invalidation levels and post-trade notes are persisted per
  trade and editable from the portfolio panel.
- Full-history deterministic journal statistics are included in portfolio and
  AI journal-review context.
- Chat streams NDJSON text deltas and closes the upstream OpenAI stream when the
  browser cancels; memory is written only after successful completion.
- Market context caches quote, news and technical components independently and
  reports fresh/cached/stale/unavailable status.
- Offline quality fixtures cover risk language, missing-data honesty and
  concentration guidance.

## Portfolio intelligence patch

- Security profiles enrich positions with sector, industry and asset class.
- `portfolio_snapshots` stores one real equity observation per UTC day.
- Risk metrics remain unavailable until the minimum real sample exists.
- Benchmark series are normalized to percentage return from the first stored
  portfolio observation and cached like other market context.
- Position-size and target-weight rebalance endpoints return simulations only;
  neither endpoint calls the paper trader's buy/sell methods.

## Strategy tooling patch

- Backtest signals use prior-bar information and execute at the next bar open to
  avoid same-close look-ahead bias.
- Backtests are long-only, disclose friction assumptions and never invoke paper
  trade execution methods.
- Saved strategies and alert state use the shared WAL-mode SQLite database.
- Alert polling is browser-local at 60-second intervals; persistent background
  scheduling remains a future platform/deployment feature.
- Earnings, analyst and insider feeds cache independently so one unavailable
  provider surface does not erase the other research sections.

## Platform patch

- `platform.db` stores account/session metadata only; each user's Orion state is
  physically isolated in `data/users/<uuid>/orion.db` via request-scoped proxies.
- The first registered user receives a copy of a legacy `data/orion.db` when it
  exists. Copying is one-time and later users never share that file.
- Session cookies are opaque, HttpOnly and SameSite Strict. Mutating protected
  requests require the matching session CSRF token.
- Alpaca keys are never persisted and the base URL is hardcoded to the paper
  endpoint. Order submission has two independent operator/user gates.
- Production deployments must use HTTPS and set secure-cookie, registration and
  exact-origin environment values described in the README.
- The PWA service worker excludes `/api/` requests from caching.

## Autonomous paper-agent patch

- The selected workspace source controls portfolio displays, intelligence,
  simulators and Orion portfolio context. Local and Alpaca ledgers are never
  merged.

## Trading-terminal UX patch

- Eight feature workspaces replace the long vertically stacked dashboard and
  use `#/overview`, `#/research`, `#/orion`, `#/opportunities`,
  `#/portfolio`, `#/strategies`, `#/learn` and `#/automation` deep links.
- Desktop uses a persistent left rail; screens at 900 px and below use a fixed
  bottom tab bar with safe-area padding.
- The persistent context strip exposes selected ticker, active ledger, Alpaca
  connection and autonomy state. A global kill action appears whenever the
  autonomous runtime is not Off.
- Research-only quote and news polling stops when that workspace is hidden. A
  lightweight `/autonomy/summary` request maintains global mode and approval state.

## Advanced chart and broker-first summary patch

- Candle payloads now include volume and reject unsupported provider ranges or
  intervals before making a market request.
- The chart uses distinct price and volume scales, supports mouse/touch pan and
  zoom, and calculates SMA/EMA overlays in the browser from the loaded bars.
- Crosshair details distinguish each bar's OHLC, previous-close change, range
  and volume; the period summary describes only the currently loaded range.
- A successful Alpaca connection explicitly selects the Alpaca workspace. The
  local simulator is preserved but is no longer presented as the primary account.

## Autonomous discovery v2 and learning-center patch

- Market-wide discovery combines held symbols, balanced live screeners and a
  deterministic rotating universe slice. Per-user rotation state is in memory;
  persistent recent-proposal and scan-coverage tables prevent restart behavior
  from collapsing back to the same small group.
- Snapshot filtering remains deterministic. Deep AI analysis is bounded to 1–10
  finalists per cycle and the UI makes that cost/coverage boundary explicit.
- Finalist selection prioritizes held-position safety, then explores fresh
  discovery, positive momentum, pullbacks/reversals and liquidity leaders.
- HOLD bypasses execution checks because it proposes no order. Only BUY/SELL can
  become `risk_rejected`; the guardian still exclusively controls eligibility,
  quantity, limits, market hours and submission.
- Autonomous prompt v2 defines confidence as confidence in the chosen action
  and records setup type, factors and missing confirmation.
- The Learn workspace is static, searchable educational content and never
  changes signals, risk limits or order behavior.

## Horizon research, chart-time and order-review patch

- The Opportunities workspace triggers an explicit scan only when requested.
  It reuses rotating Alpaca discovery and deterministic screening, then supplies
  only a bounded evidence set to the structured opportunity-board prompt.
- Day, swing and long-term horizons have distinct evidence instructions.
  Candidate cards expose news context, entry confirmation, invalidation, risks
  and limitations. Follow-up chat receives the displayed board and active paper
  portfolio, but has no execution path.
- Manual Alpaca submission no longer uses a typed phrase. The browser creates a
  review card and only a second explicit confirmation sends `confirmed=true`;
  the backend still fails closed unless the independent environment flag is on.
- Intraday candles are serialized as UTC epochs after interpreting naive
  provider timestamps as New York exchange time. The UI can format them in
  exchange or browser-local time and does not synthesize a live candle when the
  provider history is outside the current interval.
- Every learning term has mechanics, an example and combination guidance.
  Strategy playbooks include process, risk and exit sections.
- v0.17.1 gives structured horizon boards a 6,000-token minimum response budget;
  the general Orion answer budget remains configurable and concise. Invalid or
  truncated board JSON is translated into an actionable retry message.
- v0.17.2 calls the scanner with no held-symbol priority for Opportunities,
  broadens the pass to 100 live/rotating inputs and eight deep verdicts, and
  attaches source/coverage metadata. Automation continues to prioritize held
  positions because exit monitoring belongs there.
- Lightweight Charts uses `localization.timeFormatter` for crosshair labels but
  `timeScale.tickMarkFormatter` for visible axis labels. Both now use the same
  selected timezone; changing the toggle reapplies both formatters.
- The shipped Alpaca broker remains paper-only. Funded-account integration is
  intentionally outside the product boundary; never make the Paper base URL
  configurable.

## Opportunity history and assistant-only visual patch

- `opportunity_boards` stores complete board JSON, horizon and timestamp in each
  user's existing SQLite database. The history endpoint reads through the
  request-scoped `AutonomyStore`, preserving physical user isolation.
- Successful scans are persisted before the response returns. The React panel
  restores the newest board per horizon and lets users reopen any of the latest
  30 snapshots; automation orders do not mutate these records.
- v0.19 removes the Live broker module, routes, configuration and UI completely.
  A structural route test asserts that `/broker/alpaca-live/*` is absent and
  returns 404.
- OrionTrader is now explicitly a research, portfolio-intelligence and guarded
  Paper-testing workspace. Funded execution is a human action in an external
  broker, and no Live keys are accepted.
- The orbital visual system adds an aurora/grid backdrop, glass panels, a focused
  Overview hero, clearer workspace descriptions, a redesigned sign-in surface
  and responsive/reduced-motion behavior.
- Alpaca assets and screeners reduce the tradable universe before deep AI calls;
  Orion never receives thousands of raw symbols in one prompt.
- AI returns BUY/SELL/HOLD proposals only. `RiskGuardian` owns quantity and
  limit-price calculations and can reject every proposal independently.
- Autonomous orders require both `ALPACA_ORDER_SUBMISSION_ENABLED=true` and
  `ORION_AUTONOMY_ENABLED=true`; approval mode still requires a human phrase.
- Runtime automation state is memory-only and restarts Off. Settings, proposals
  and audit events remain in the per-user database.
- The kill switch cancels open orders whose client ID starts with `orion-auto-`.
  It does not liquidate positions or cancel unrelated Alpaca orders.

## Risk-profile recommendation patch

- `risk_tolerance` remains the single per-user profile key shared with Orion
  preferences. Dedicated GET/PUT endpoints expose the deterministic policy and
  validate Conservative, Balanced or Aggressive values.
- Optional `recommendation_planning_equity` and
  `recommendation_planning_cash` values are saved in the user's existing
  preferences table. They are USD-equivalent planning inputs, not broker
  credentials or synchronized balances.
- Opportunity-board structured output now includes optional numeric entry, stop
  and target levels. The prompt explicitly prohibits instrument, leverage,
  margin, quantity and account-risk decisions. The selected mode is not supplied
  to the ranking prompt, so changing risk tolerance cannot inflate setup quality.
- `recommendation_engine.py` rejects weak ratings, low setup quality, stale
  context, invalid levels, distant entries and inadequate reward-to-risk before
  calculating any quantity.
- Quantity is risk-sized from stop distance plus slippage and then capped by
  profile exposure and available cash.
- v0.31 caps Conservative, Balanced and Aggressive at 1x. Existing schema keys
  are retained so historical boards still render, but new CFD and borrowed-
  exposure suggestions are disabled until replay, execution and walk-forward
  validation pass.
- The entire plan, sizing source and audit gate list are stored inside each
  immutable opportunity-board snapshot. Changing the profile affects new scans
  without rewriting history.
- Large feature workspaces are loaded with React `lazy`/`Suspense`, keeping the
  initial production bundle below the previous single-chunk warning threshold.

## Required verification

```bash
pytest backend/tests
cd backend && ../.venv/bin/python -m evals.run_quality_evals && cd ..
cd frontend
npm test
npm run build
```

Do not commit `.env`, `backend/data/*.db`, `node_modules`, `dist`, or caches.
