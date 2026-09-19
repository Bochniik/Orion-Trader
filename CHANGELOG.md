# Changelog

## Unreleased — Orion 24/7 Intelligence

- Added one authoritative session-state contract for regular, premarket, after-hours and closed research modes.
- Core now uses the Alpaca clock plus NYSE calendar instead of a duplicate hard-coded session classifier; early closes, weekends and holidays degrade safely.
- Added `GET /core/session` with workflow priority, next transition, next regular open, price semantics and allowed research workflows.
- Today now switches to a research/review/preparation workspace outside regular hours instead of presenting an empty live-trading surface.
- Closed-market UI shows next-session timing in the user's browser-local time, watchlist research queue and explicit live/extended/historical data semantics.
- Added backend session-switching tests, frontend polling/dashboard regressions and a dedicated build/CI gate.
- No production model, calibration, decision gate, risk rule or broker execution behavior changed.

## Unreleased — Orion news intelligence

- Analyze the already-loaded Analyze-workspace news in one bounded Orion AI batch.
- Show per-article POSITIVE / NEGATIVE / MIXED / NEUTRAL context, a concise digest, up to three key points and a short "why it matters" explanation.
- Preserve provider summaries from Yahoo Finance when present; fall back explicitly to headline-only analysis when no summary text is available.
- Keep sentiment separate from price-direction prediction and trading recommendations; the feature does not fetch arbitrary article bodies or submit orders.
- Fail non-blockingly when Orion AI is unavailable: the underlying news feed remains readable.
- Added focused backend/frontend tests and a dedicated CI gate.

## 2.4.0 — Unified decision radar (2026-09-02)

- Preserved valid deterministic directional probabilities separately from final trade permission, so blocked decisions explain their confidence instead of displaying a misleading blank.
- Added liquidity-first Opportunity Radar categories: gainers, losers, most active, unusual volume, inferred quote pressure, momentum, statistically confirmed dislocations, and breakout watch.
- Added staged Today refresh every 30 seconds while visible, with opt-in sound and cooldown-protected Orion Prime alerts.
- Added structured Orion Prime criteria requiring Tier A liquidity, strong calibrated evidence, model agreement, positive post-cost edge, supportive regime and no blockers.
- Retained assistant-only operation and explicit provider limitations.

## 2.3.0 — Point-in-time evidence and decision quality (2026-09-02)

- Added per-user received-time evidence ledger with immutable correction history.
- Added frozen forward-outcome policy and exact same-source settlement.
- Added conservative descriptive quality report and My Stocks panel.
- Added explicit `check_outcomes` research job; legacy decisions remain unscored.
- Preserved assistant-only, no-order safety boundary.

## 2.0.0-m2 — One-action Decision Orchestration (2026-09-02)

- Bounded, per-user cancellable background analysis with real stage reporting.
- Automatic dataset preparation and gated model promotion on explicit actions.
- Purged cross-symbol train/calibration/holdout boundaries; horizon-gap protection.
- Completed-minute availability and source-specific feature freshness.
- Immutable final-decision history, including WAIT; isolated saved-plan checks.
- Optional one-minute monitoring while My Stocks is open and visible.
- No new primary screens, order path, paid AI call or profitability claim.

## 2.0.0-m1 — Simplified Core Experience

- Replaced ten primary workspaces with Today, Analyze and My Stocks; old deep
  links map to these workflows, with Today as the default home.
- Added reusable conclusion-first opportunity cards with optional evidence,
  original model outputs and constrained on-demand Orion explanations.
- Added a small authenticated core API facade and deterministic decision adapter.
  Existing model permission remains authoritative; technical-only evidence
  cannot create a probability or approved entry plan.
- Capped Today at five distinct Tier A/B tickers. Preserved liquidity-first
  sampling, vetoed conflicting or unavailable horizons, and withheld stale
  quotes/features, missing/invalid levels and insufficient reward/risk.
- Retained underlying historical feature timestamps beneath stream overlays.
  Expired displayed cards become WAIT, rather than retaining active levels.
- Preserved chart ranges/overlays, search, per-user watchlists, positions, journal,
  authentication, CSRF and all legacy APIs. No user-data migration or deletion.
- Removed model-builder, lab, broker-order and agent controls from primary UI;
  useful specialist components remain in source but are not production imports.
- Added data-only connection settings, race-safe ticker requests and serialized
  watchlist edits. Service-worker caching excludes APIs and cross-origin data.
- Corrected the Vite 8 / Vitest 4 JSX runtime configuration mismatch.
- Added full architecture audit, decision-history design and the next milestone.
- Browser smoke coverage is included but could not run here: Chromium was absent
  and its download timed out. See CHECK_REPORT for exact completed validation.

## 0.35.0 - Liquidity-First Live Edge and Orion Learning Brain

- Added a dedicated chosen-stock mode to Live Edge. A normalized user ticker is
  pinned into the fresh broker-universe sample and analyzed for only the
  selected horizons.
- Fixed low-liquidity board dominance by ranking a 60-100 symbol discovery
  batch, exhausting most-active candidates before percentage movers, sorting
  every board section by absolute LiquidityScore and showing Tier A/B research
  rows before any Tier C/D observations.
- Added a separate high-liquidity research-watch section for Tier A/B stocks
  whose model, cost, regime, strategy or memory gates correctly return HOLD.
  Lower-liquidity NO TRADE observations remain available in a collapsed audit
  and cannot displace the liquid board.
- Added fourteen auditable mathematical strategy families: EMA trend, SMA
  slopes, multi-horizon momentum, acceleration, VWAP, RSI mean reversion,
  volatility expansion/contraction, volume confirmation, quote imbalance,
  opening range, intraday/previous-day breaks and market-relative strength.
- Added weighted LONG/SHORT/NEUTRAL strategy consensus with formulas, evidence,
  unavailable states and a strict boundary that strategy voting never alters
  calibrated probabilities.
- Added per-user outcome-learning memory. Every settled prediction records the
  model decision, actual direction/return, after-cost result, strategy votes
  and context signature. Good and bad outcomes create Bayesian-shrunk profiles,
  bounded strategy-weight adjustments and adverse-pattern vetoes.
- Positive memory cannot override model reliability, calibration, liquidity,
  cost, regime or NO TRADE gates. The memory remains cold until sufficient
  comparable observations exist and can be cleared independently.
- Added BUY/SELL/HOLD research interpretation. SELL is explicitly bearish or
  reduce-existing-long research, never an automatic short or order action.
- Passed 228 backend and 54 frontend regression tests.

## 0.34.0 - Orion Predictive Intelligence v1

- Completed phases 2-11 without connecting predictions to an order path.
- Added an extensible historical/real-time feature schema covering sub-minute
  and multi-minute returns, momentum and acceleration, EMA/SMA slopes, VWAP,
  RSI, ATR, realized volatility, volume pace, quotes, imbalance, opening range,
  session levels, market/sector momentum and relative strength.
- Kept unsupported sub-minute evidence null. One-minute historical bars are
  never relabeled as thirty-second observations or targets.
- Added leakage-controlled UP/DOWN/NEUTRAL samples for one-minute through
  one-hour horizons with volatility/spread-aware neutral bands.
- Added a deterministic ensemble of multinomial logistic regression and
  gradient-boosted decision stumps, chronological train/calibration/untouched
  holdout blocks, three expanding walk-forward folds and held-out temperature
  calibration. Random splits and neural networks are absent.
- Added bounded deterministic model budgets suitable for desktop operation and
  persisted dataset/model provenance per user.
- Added explicit long/short expected value after full-spread and estimated
  round-trip slippage, plus deterministic bullish/bearish/range/high-volatility/
  low-volatility market-regime classification.
- Added OrionOpportunityScore from calibrated direction, EV, liquidity,
  feature quality, calibration, market/sector alignment and execution quality.
- Added progressive Tier A-D evidence gates and exact
  `NO TRADE — NO STATISTICAL EDGE` behavior. Entry, invalidation and target
  research levels remain withheld whenever any gate fails.
- Added the tenth terminal workspace, Orion Live Edge, with primary liquid and
  explicitly elevated-risk lower-liquidity sections.
- Added a per-user Prediction Laboratory with due-outcome settlement, overall
  and subgroup accuracy, precision, recall, Brier score, calibration buckets,
  predicted/realized return, EV and simulated after-cost P&L.
- Laboratory metrics remain provisional before 500 settled live observations,
  and model horizons remain experimental until every out-of-sample gate passes.
- Added optional structured Orion explanations downstream of immutable numeric
  results. The model has no numeric output fields; attempted numeric restatement
  is rejected, and the backend returns the unchanged evidence plus SHA-256.
- Expanded regression coverage to 222 backend and 54 frontend tests.

## 0.33.0 - Predictive Intelligence Phase 1: Liquidity Engine

- Added a deterministic bounded-universe liquidity service for Orion
  Predictive Intelligence v1. It does not call an LLM, prediction model or
  broker order method.
- Added 20-session average dollar volume, current dollar volume, time-adjusted
  relative volume, quoted spread/basis points, trade frequency, current and
  average volume rates, daily realized volatility and batch-relative
  liquidity percentile.
- Added an auditable 0-100 LiquidityScore with factor points, data provenance,
  evidence coverage, missing-data penalties and Tier A/B/C/D classification.
- Tier A is sorted first. Future lower-liquidity model gates require
  progressively higher directional probability, edge after costs and
  out-of-sample observations; these gates are explicitly not reliability
  claims or current predictions.
- Added a bounded Alpaca Paper research sampler using approximately 70% live
  activity priority and 30% per-user rotating full-universe exploration.
- Added partial-failure reporting for live screeners, quote snapshots and
  adjusted daily OHLCV history. The IEX snapshot/feed limitation is disclosed.
- Excluded the current incomplete daily session from historical baselines and
  require at least ten completed sessions before history-dependent evidence can
  earn points.
- Added authenticated status, ranking, compact history, full-detail restore and
  deletion APIs with per-user SQLite isolation.
- Added frontend API contracts for the future Live Edge interface without
  prematurely exposing Phase 8 prediction UI.
- Kept every probability field null and labeled inactive. No UP/DOWN/NEUTRAL,
  expected-value, opportunity-score or reliability output exists until later
  walk-forward and calibration phases are implemented and validated.
- Expanded regression coverage to 210 backend and 52 frontend tests.

## 0.32.0 - Professional Execution Stress Lab

- Added a separate Execution Lab beside Live Scanner and Replay Lab, creating a
  compact three-stage research workflow instead of another long page.
- Added seven reproducible scenarios: baseline, wide spread, adverse opening
  gap, thin liquidity/partial fill, LULD-style interruption, broker/venue
  rejection and combined execution stress.
- Added explicit market/limit order assumptions, side-aware pricing, half-
  spread cost, square-root participation impact, scenario liquidity capacity
  and deterministic limit-price quantity solving.
- Added protective-stop stress showing planned versus modeled stop fill,
  risk/share and risk-expansion multiple under gaps and friction.
- Blocked pause and rejection scenarios report unknown execution cost rather
  than treating no fill as a free zero-cost outcome.
- Added an explicit regulatory boundary: the LULD-style scenario blocks
  immediate fills but never claims to reproduce an official historical band,
  NBBO state, exchange pause tape, reopening auction or queue position.
- Added formula, limitation, probability-null and zero-order-route audits to
  every result. The service imports no broker adapter and reads no credentials.
- Added per-user SQLite simulation history with summary-first listing, complete
  restoration and confirmed deletion independent of scan/replay history.
- Added one-click Replay-to-Execution handoff using only cutoff-safe anchor
  close and preceding 20-session average volume.
- Expanded regression coverage to 195 backend and 51 frontend tests.

## 0.31.0 - Extreme-Mover Replay Lab

- Added a separate Replay Lab mode beside the live Move Lab scanner so current
  evidence and historical validation cannot be mistaken for one another.
- Added a cutoff-controlled historical preparation score using only daily
  OHLCV available by each decision close: volume, volatility contraction,
  trend, base/resistance structure and relative strength versus SPY.
- Added isolated forward outcome windows for observed 20%, 50% and 100% highs,
  time-to-threshold/peak, maximum low, ending return and normalized return paths.
- Added configurable one-, two- and five-year samples, 10-60 session outcome
  windows, five- to 20-session anchor strides and an auditable flag threshold.
- Added score-band counts, descriptive frequencies, a fixed chronological 70/30
  display, non-overlapping extreme examples, false positives and missed moves.
- Added explicit leakage controls that exclude current profiles, fundamentals,
  news and filings from historical scores and keep future rows out of features.
- Added prominent survivorship, delisting, adjusted-history, overlapping-window,
  missing-event-data and non-executable-high limitations. Probability outputs
  remain null and historical frequencies are never labeled as forecasts.
- Added per-user SQLite replay history with summary-first loading, full audit
  restoration and confirmed history deletion.
- Made adjusted-bar retrieval explicit in the market-data adapter to prevent a
  provider default change from silently altering strategy/replay inputs.
- Preserved the research-only boundary: Replay Lab has no order service, route
  or execution handoff.
- Expanded regression coverage to 182 backend and 49 frontend tests.

## 0.30.0 - Durable Alpaca streaming evidence

- Added explicit, per-user Alpaca market-data and news WebSocket sessions for
  the bounded Move Lab candidate set, with IEX, SIP and delayed-SIP selection.
- Added authentication, channel-level state, exponential reconnect/backoff,
  fatal entitlement and connection-limit handling, last-frame/data ages,
  sequence cursors and bounded-buffer drop counters.
- Kept market quotes, optional trades and bars in bounded process memory while
  deduplicating normalized public news into the existing per-user SQLite event
  audit. Broker credentials remain memory-only and are redacted from every
  status, error, event and metric contract.
- Added explicit start, subscription-update, stop, status and incremental event
  endpoints. Starting is never automatic; logout, Alpaca disconnect, backend
  shutdown and the maximum session runtime stop the connection.
- Integrated fresh streamed quote/bar/news evidence into scans with the prior
  snapshot pipeline preserved as fallback. Active subscriptions rotate to the
  next scan's top 16 assessments.
- Added Move Lab feed controls, channel health, reconnect/error disclosure,
  an incremental live evidence tape and streamed-evidence candidate badges.
- Added stream sessions, connected channels, reconnects, messages and dropped
  events to Prometheus-style backend metrics.
- Kept all streaming research/shadow-only: no event can prepare, approve or
  submit an order, all probabilities remain uncalibrated and leverage remains
  disabled.
- Expanded regression coverage to 175 backend and 46 frontend tests.

## 0.29.0 - Explosive-Move Intelligence foundation

- Added a dedicated Move Lab with separate PreMoveScore, IgnitionScore and
  DangerScore cards; the scores are never merged into a buy score.
- Added deterministic preparation, intraday ignition, failed-breakout,
  dilution, distress, spread, liquidity and float-risk evidence with factor-
  level source and availability audits.
- Added category classification and distinct watch/danger thresholds for
  liquid large caps, liquid small caps, recent IPOs, biotechnology catalysts,
  low-float momentum names and distressed/compliance-risk securities.
- Added an SEC EDGAR submission-metadata client that is disabled until a
  declared `SEC_USER_AGENT` contact is configured, caches responses and
  self-throttles below the SEC fair-access ceiling.
- Added normalized event storage for Alpaca news snapshots, Alpaca corporate-
  action snapshots and SEC filing metadata, including source identifiers,
  timestamps, classification, materiality, novelty and reaction latency.
- Added configurable bounded rotating broker-universe scans with transparent
  coverage, data-freshness, missing-feed and category-rejection reporting.
- Added per-user SQLite scan history and an audit-preserving normalized event
  log; clearing visible scan history does not delete event evidence.
- Added Adaptive Risk v1 with ATR-based stops, category exposure caps, drawdown
  and concentration reductions, slippage and catastrophic-gap assumptions,
  explicit limiting factors and valid Reject Trade/zero-size outcomes.
- Disabled borrowed-exposure and CFD suggestions across every existing risk
  profile. All research sizing is capped at 1x until realistic execution replay
  and date-split walk-forward validation pass.
- Left persistent WebSocket ingestion, realistic execution simulation,
  extreme-mover replay, two-stage alerts and calibrated probability models
  explicitly inactive for later isolated phases instead of presenting stubs as
  production capabilities.
- Expanded regression coverage to 162 backend and 45 frontend tests.

## 0.28.0 - Catalyst Breakout Radar

- Added a third Opportunities scan intent for auditable catalyst and breakout
  readiness across the selected broker's mapped tradable universe.
- Added a deterministic 100-point checklist for float, multi-session volume,
  tight consolidation, ATR contraction, relative strength versus SPY, mapped
  sector momentum, recent insider purchases and fresh/upcoming catalysts.
- Requires at least 80 observed points and 80% usable evidence for the
  high-potential watch label. Missing or stale fields receive zero points.
- Added seven-day headline and 180-day insider-purchase freshness windows;
  headline keywords remain explicitly unverified until the primary source is
  reviewed.
- Enriched provider profiles with normalized float, shares, market cap,
  short-interest and recent-volume fields. Short interest is risk context and
  never positive score points.
- Added a bounded catalyst starter list without hardcoding discovery: only part
  of each batch is reserved for listed symbols and the rest continues rotating
  through the full connected broker universe.
- Added per-candidate score, evidence coverage, factor audit, microstructure,
  warnings and missing-feed disclosures to current and saved boards.
- Kept deterministic market structure, Orion evidence review, entry timing and
  risk-profile gates independent; a high readiness score cannot create an order
  or override those controls.
- Expanded backend route, scanner, scoring, provider-normalization, prompt and
  server-rendered frontend coverage.

## 0.27.0 - Deterministic Research Strategy Lab

- Added a dedicated, horizontally selectable Strategy Lab to the Research
  workspace rather than extending the page into another long vertical feed.
- Added written setup, trigger, exit, evidence, checklist, blocker and risk
  contracts for trend-following momentum, relative-strength trend pullback,
  catalyst plus five-minute opening-range breakout, regime-filtered mean
  reversion, volatility-contraction breakout, pairs screening and long-term
  diversified investing.
- Added recent Golden Cross confirmation and Death Cross defensive monitoring
  using 50/200-session SMAs. Golden Cross remains a lagging regime event that
  needs entry confirmation; Death Cross never creates an automatic short.
- Added deterministic entry, invalidation, 2R target and reward/risk levels only
  for triggered, aligned or forming long setups. Unaligned setups fail closed
  without actionable levels.
- Added SPY regime, relative strength, dollar-volume, ATR, RSI(2), VWAP, gap,
  opening-range, relative-volume and headline-risk checks with freshness-aware
  partial-provider handling.
- Added optional peer-ticker divergence research with an explicit warning that
  correlation and a spread z-score do not prove cointegration.
- Defined every displayed score as required-rule completion—not confidence,
  certainty or probability of profit—and counts unavailable required evidence
  as unconfirmed.
- Linked Research directly to Orion follow-up and the existing historical
  backtester; documented 50/200 SMA settings for Golden/Death Cross backtests.
- Expanded deterministic, endpoint, API-client and server-rendered UI coverage
  to 145 backend and 43 frontend tests.

## 0.26.0 - Entry-ready opportunity scanner

- Added an explicit **Entry-ready now** Opportunities mode alongside the wider
  quality-setup scan.
- Added a deterministic readiness audit for current quote versus entry zone,
  technical quality, trend, liquidity, volatility, reward-to-risk, breakout,
  relative volume and maximum chase distance.
- Uses the current scanner quote for entry-zone validation when available,
  while retaining the latest candle close and price source for auditability.
- Keeps technical readiness separate from Orion's evidence review and the
  selected deterministic risk profile. A candidate is marked entry-ready only
  after all three stages pass.
- Revalidates the highest-ranked banner after the final risk plan, preventing a
  chart-confirmed setup from appearing actionable when a later gate rejected it.
- Shows an honest zero-match result and the closest monitored setups instead of
  weakening standards to manufacture a recommendation.
- Persists scan intent in opportunity history and restores all-mode and
  entry-ready boards independently.
- Updated the opportunity prompt to treat readiness as a technical pre-check,
  never certainty or probability of profit.
- Expanded backend/API/UI regression coverage to 138 backend and 41 frontend
  tests.

## 0.25.0 - Hybrid opportunity intelligence

- Added horizon-specific deterministic OHLCV analysis before Orion ranking:
  15-minute structure for day trading, six-month daily structure for swing
  trading and two-year daily structure for long-term research.
- Added reproducible ATR, support, resistance, trend, momentum, relative-volume,
  liquidity, volatility and breakout-structure component scores.
- Added concrete entry zone, breakout trigger, protective stop, research target
  and expected reward-to-risk levels whenever market structure is sufficient.
- Replaced the generic “plan incomplete” state with explicit confirmed,
  waiting-for-breakout, extended/retest, below-standard, sizing-unavailable and
  data-insufficient decisions.
- Added a deterministic finalist pass before bounded Orion review, increased
  each rotating scan to 160 instruments and evaluates up to 16 finalists before
  sending the strongest eight evidence sets to the model.
- Added hybrid ranking that blends reproducible market structure with Orion's
  news/profile/portfolio critique, preserves both component scores and prevents
  unsupported model confidence from overriding missing or weak chart evidence.
- Added a highest-ranked-setup summary and complete level/audit presentation to
  the Opportunities UI while keeping every result research-only.
- Separated critical OHLCV availability from optional news/profile failures, so
  a missing optional feed no longer erases an otherwise valid price plan.
- Added explicit instrument-to-account FX conversion for recommendation sizing;
  levels remain visible and sizing fails closed when conversion is unavailable.
- Expanded deterministic, API, prompt and server-rendered UI regression
  coverage to 136 backend and 41 frontend tests.

## 0.24.0 - Trading 212 opportunity universe

- Added Automatic, Trading 212 Demo and Alpaca Paper universe selection to the
  Opportunities workspace, with disconnected sources clearly disabled.
- Added a cached Trading 212 instrument-universe loader that preserves exact
  broker tickers while mapping supported exchanges to independent market-data
  symbols for research only.
- Added bounded 100-instrument batch screening, rotating per-user/per-broker
  coverage and up to eight deep Orion classifications instead of uncontrolled
  quote or AI fan-out across thousands of assets.
- Added broker instrument totals, mapped coverage, unsupported mappings, quote
  failures, exact Trading 212 tickers and source labels to current and saved
  opportunity boards.
- Scoped recent-symbol deprioritization and cumulative coverage by broker
  source, so Alpaca and Trading 212 scan histories never distort each other.
- Added partial market-data failure handling and fail-closed cross-currency
  position sizing while keeping valid research candidates visible.
- Kept Trading 212 opportunity discovery strictly research-only. It adds no
  autonomous Trading 212 route and does not change the Demo-only execution
  boundary.

## 0.23.0 - Trading 212 Demo confirmed execution

- Added fixed, documented Trading 212 Demo market, limit, stop, stop-limit and
  numeric-ID cancellation contracts without adding a Live host or environment
  switch.
- Added instrument-directory search and exact broker-ticker selection.
- Added disabled-by-default submission policy, account-currency FX conversion,
  per-order, cash, position concentration, daily count and daily notional
  limits, plus duplicate-order protection.
- Added short-lived review and explicit confirmation. Confirmation revalidates
  every gate and atomically claims the review to prevent double submission.
- Added unknown-outcome fail-safe behavior with no automatic retry, unique
  reconciliation recovery, persistent broker states and separately confirmed
  cancellation.
- Added idempotent synchronization of reconciled Demo fills and their original
  thesis/invalidation into Orion's per-user external journal.
- Added a complete Paper Lab workflow for portfolio data, instrument selection,
  review gates, tracked orders, reconciliation and cancellation.
- Kept Trading 212 physically absent from autonomous execution and kept all
  credentials per-user, backend-memory-only and non-persistent.
- Expanded the full regression suite to 118 backend and 39 frontend tests.

## 0.22.0 - Trading 212 Demo active portfolio intelligence

- Promoted a connected Trading 212 Demo account to a selectable active
  portfolio source alongside Local Simulator and Alpaca Paper.
- Normalized Demo cash, account value, positions, profit/loss and currency into
  Orion's portfolio contract so chat, portfolio review, daily briefing, health
  scoring, exposure, performance, sizing and rebalancing use the selected
  account.
- Anchored per-position account values to Trading 212's broker-reported
  invested total when the API omits direct values, avoiding false EUR/USD
  assumptions and marking estimated allocations explicitly.
- Added broker-specific Overview, Portfolio and context-bar presentation with
  account-currency formatting and read-only workspace switching.
- Classified optional 403 feed permissions separately from connection errors,
  preserving a healthy core account while clearly naming unavailable feeds.
- Kept Alpaca Paper as the only automation and in-app order adapter. Trading
  212 remains fixed to Demo, GET-only, memory-only and structurally incapable
  of order submission or cancellation.
- Added regression coverage for source selection, disconnect fallback,
  normalization, permission metadata and the absent execution surface.

## 0.21.0 - Trading 212 Demo read-only mirror and history controls

- Added a per-user, memory-only Trading 212 Demo connector fixed to the official
  Demo host and an explicit allow-list of documented GET endpoints.
- Added a read-only Paper Lab panel for account cash/value, positions, pending
  orders, historical orders, transactions and dividends.
- Added short-lived snapshot caching, freshness metadata and partial-feed
  failure handling to reduce rate-limit pressure without hiding stale state.
- Added no Trading 212 Live host, environment switch, order submission,
  cancellation or generic HTTP method path; structural tests enforce the
  read-only boundary.
- Added confirmed per-horizon and all-board deletion to Opportunities.
- Added Paper Lab “clear visible history” with an agent-off/pending-approval
  guard. Proposal and event audit rows remain preserved in SQLite.
- Expanded backend, API-client and server-rendered UI regression coverage.

## 0.20.0 - Risk-profile recommendation engine

- Added per-user Conservative, Balanced and Aggressive recommendation modes
  with explicit risk, exposure, leverage, quality and reward-to-risk ceilings.
- Added a deterministic recommendation engine that treats Orion's structured
  entry, stop and target as untrusted inputs, validates them, and owns quantity,
  notional exposure, estimated loss and margin calculations.
- Kept Conservative and all Long-Term plans real-shares-only. Balanced can mark
  a 2x CFD optional only for exceptional same-session setups; Aggressive reaches
  3x only behind stricter quality, reward, spread and daily-move gates.
- Added optional per-user USD-equivalent planning equity and cash, avoiding
  misleading external sizing from the default $100,000 Alpaca Paper account.
- Added complete pass/fail gate explanations, warnings, sizing source and
  external-execution boundary to every saved opportunity board.
- Expanded Learn with detailed Leverage, CFD and Margin explanations.
- Split the heaviest workspaces into lazy-loaded production chunks, reducing the
  initial application bundle while preserving PWA behavior.
- Added deterministic calculation, persistence, API, structured-prompt and
  server-rendered UI regression tests.

## 0.19.0 - Assistant-only boundary and visual refresh

- Removed the Alpaca Live client, in-memory Live credential handling, Live API
  routes, environment gate and Live account interface. OrionTrader accepts no
  Live keys and exposes no funded-order path.
- Kept Alpaca Paper as an isolated testing environment for manual safeguards,
  Shadow mode, Approval mode and bounded autonomous-paper experiments.
- Added a broker-neutral external execution handoff: research, validate, check
  portfolio impact, execute personally in the chosen broker and journal the
  result.
- Reworked the visual system with an orbital Orion identity, aurora backdrop,
  glass surfaces, clearer workspace descriptions, richer context cards and
  responsive navigation.
- Added a focused Overview hero, redesigned authentication experience, visible
  assistant-only status and a dedicated execution-boundary panel in Paper Lab.
- Added reduced-motion behavior, stronger keyboard focus states and regression
  tests for the assistant-only presentation contract and absent Live routes.

## 0.18.0 - Persistent opportunity history

- Added per-user SQLite opportunity-board history. Every successful Day, Swing
  or Long-Term scan is saved as an immutable snapshot and restored after
  navigation, paper/automation orders, browser refreshes and backend restarts.
- Added a Saved Opportunity History interface with horizon, timestamp and
  candidate previews. Selecting an older board restores its full research,
  limitations and board-specific Orion assistant context.
- Added regression tests for history persistence and per-user route behavior.

## 0.17.2 - Independent universe research and chart-axis time

- Removed owned positions from the Opportunities discovery priority. Horizon
  research now starts from live market leaders plus a rotating slice of every
  active tradable Alpaca US equity; owned stocks can appear only if they qualify
  through the same independent process.
- Broadened each horizon pass to 100 screener/discovery inputs, up to 200
  snapshot symbols and eight deep classifications. Orion now returns a Strong,
  Watch or Avoid verdict for every supplied finalist rather than hiding weak
  ideas.
- Added explicit research-scope, batch coverage, cumulative distinct-symbol
  coverage and discovery-reason metadata to the opportunity interface.
- Fixed the candlestick chart's visible time-axis labels. The axis formatter now
  follows the same New York/local timezone selector as the crosshair inspector.

## 0.17.1 - Opportunity-board completion fix

- Raised the structured-output budget specifically for Day, Swing and Long-Term
  opportunity boards so multi-candidate JSON is not truncated by the general
  concise-answer limit.
- Replaced raw SDK/Pydantic JSON validation output with a short actionable
  message if a provider response is still incomplete. Failed board generation
  remains research-only and never creates an order.
- Added regression coverage for the board token budget and truncated-output
  error handling.

## 0.17.0 - Horizon research, safer order review and market time

- Added a dedicated Opportunities workspace for Day Trading, Swing Trading and
  Long-Term research. Each on-demand scan uses rotating Alpaca discovery,
  deterministic screening and a bounded structured Orion ranking.
- Added evidence-based candidate scores, strategy and holding-period labels,
  news context, entry confirmation, thesis invalidation, risks, scan coverage
  and an Orion follow-up assistant for each generated board.
- Kept opportunity boards research-only: they cannot size or submit orders and
  explicitly disclose missing or conflicting data.
- Removed the typed `SUBMIT PAPER ORDER` phrase from manual paper orders.
  Manual submission now uses a faster two-step review/confirm interaction while
  retaining the independent disabled-by-default server execution flag.
- Made intraday candle timestamps explicit UTC instants derived from New York
  exchange time, added New York/local display controls and prevented stale or
  after-hours quotes from fabricating candles at the browser clock.
- Expanded every glossary term with mechanics, a worked example and evidence
  combinations; expanded strategy playbooks with process, risk and exit
  frameworks and added Day/Swing/Long-Term learning guides.

## 0.16.0 - Broad-market discovery and learning center

- Replaced the narrow repeating autonomous pool with balanced Alpaca
  most-active, gainer and loser inputs plus a rotating, per-user slice of the
  complete active tradable equity universe.
- Added recent-symbol deprioritization, persistent lifetime scan coverage and
  diverse finalist selection across held positions, rotating discovery,
  momentum, pullbacks/reversals and liquidity.
- Increased discovery defaults to 50 snapshot candidates and five deep AI
  reviews. The exact legacy 25/3 default is migrated, custom settings remain
  untouched, and Focused, Balanced and Broad one-click presets are available.
- Corrected decision semantics: HOLD is now a neutral `observed_hold`, while
  `risk_rejected` is reserved for proposed BUY/SELL orders that fail a hard
  execution rule.
- Clarified that confidence applies to the selected action and upgraded the
  autonomous structured output with setup type, decision factors and the exact
  missing confirmation for HOLD.
- Added a searchable Learn workspace covering indicators, chart terms,
  execution, portfolio risk, Orion statuses and five strategy playbooks.

## 0.15.0 - Advanced market chart and broker-first account summary

- Rebuilt the candlestick chart with eight range presets, interval-aware bars,
  pan/zoom, a precise crosshair inspector and responsive mobile behavior.
- Added volume bars, SMA 20, EMA 20 and SMA 50 overlays with independent toggles.
- Added exact OHLC, bar change, percentage change, high-low range and volume at
  the crosshair plus loaded-period change, high, low and average volume.
- Added validated candle period/interval allowlists and volume to the backend
  candle contract.
- Alpaca connection now selects Alpaca Paper as the active workspace. Overview
  leads with broker equity, then cash, buying power and invested value; local
  starting cash appears only when Local Simulator is explicitly selected.

## 0.14.1 - Windows desktop shortcut

- Added a one-time desktop-shortcut installer with a dedicated OrionTrader icon.
- Added a double-click launcher that safely bypasses PowerShell execution policy
  for its own process and automatically uses fast startup after dependencies exist.
- Added launcher contract tests for shortcut targeting and startup behavior.

## 0.14.0 - Trading-terminal navigation

- Replaced the single long dashboard with six URL-backed workspaces: Overview,
  Research, Orion AI, Portfolio, Strategies and Automation.
- Added a persistent desktop sidebar and touch-friendly mobile bottom tab bar.
- Added an always-visible context strip for ticker, active account, broker and
  autonomous-agent state, including a global emergency stop when the agent runs.
- Added pending-approval badges, lightweight agent-summary polling and lazy
  quote/news loading so hidden workspaces do not continuously fetch data.
- Added detailed autonomous candidate errors to the in-app audit trail.
- Documented same-Wi-Fi phone access and the HTTPS boundary for PWA installation.

## 0.13.0 - Broker-aware autonomous Orion

- Added an explicit Local Simulator / Alpaca Paper workspace source. Cash,
  holdings, portfolio intelligence, simulations and Orion portfolio context now
  use the selected account without mixing the two ledgers.
- Added Alpaca active-asset discovery, most-active/mover screening and IEX
  snapshot filtering before bounded deep Orion evaluation.
- Added Off, Shadow, Approval and Autonomous Paper modes with an in-process
  scheduler. Runtime mode always returns to Off after a backend restart.
- Added deterministic confidence, position, order, cash, daily-loss, trade-count,
  price, volume and spread gates that AI output cannot modify.
- Added limit/day-only autonomous submission, independent server enablement,
  unique order IDs, proposal persistence, audit events and a kill switch that
  cancels Orion-created open orders without liquidating positions.
- Added broker-aware React controls, account-specific cash/portfolio displays,
  configurable risk limits and approval/audit workflows.

## 0.12.2 - Local session cookie fix

- Fixed successful registration/login being followed by protected-route 401s
  when the frontend used `localhost` but the API client used `127.0.0.1`.
- The development API client now matches the browser hostname so SameSite Strict
  session cookies remain first-party, while production continues to use `/api`.
- The Windows launcher now opens the exact `127.0.0.1` frontend origin it binds.

## 0.12.1 - Matched local startup

- Fixed stale frontend/backend mismatches after an older OrionTrader process
  remained on port 5173 or 8000.
- The Windows launcher now reports the owning process and exits before starting
  a partial service pair when either required port is occupied.
- Vite is pinned to port 5173 with strict-port mode, preventing a silent move to
  port 5174 while the launcher opens the old page.

## 0.12.0 - Platform foundation

- Added scrypt password hashing, seven-day opaque sessions in HttpOnly SameSite
  cookies, CSRF tokens, protected API routes and configurable registration.
- Added physical per-user SQLite isolation. The first account can claim the
  legacy database; subsequent accounts receive independent database files.
- Added Alpaca paper-only account/position sync. Credentials are memory-only;
  paper orders require a disabled-by-default server flag plus an exact phrase.
- Added portable backend/frontend Dockerfiles, Compose persistence and health
  checks, same-origin Nginx proxying, readiness and Prometheus-text metrics.
- Added structured request logging, request IDs and baseline security headers.
- Added an installable responsive PWA, offline application shell, install
  prompt, notification permission control and local triggered-alert notices.

## 0.11.0 - Strategy tooling

- Added deterministic long-only SMA crossover, RSI reversion and breakout
  backtests with next-bar-open execution, commission, slippage, optional
  allocation, stop-loss and take-profit parameters.
- Added equity curves, buy-and-hold comparison, return, drawdown, volatility,
  Sharpe, completed-trade and win-rate reporting.
- Added SQLite saved strategies with run/delete controls in the strategy builder.
- Added persistent price, RSI, position-allocation, portfolio-drawdown and
  thesis-invalidation alerts with one-minute checks while the app is open.
- Added independently cached earnings calendar, analyst ratings/targets and
  insider activity with partial-provider failure reporting.
- Added explicit no-execution safeguards for backtests and alerts.

## 0.10.0 - Portfolio intelligence

- Added cached security profiles and current sector/asset-class exposure.
- Added UTC-daily SQLite equity snapshots and deterministic total return,
  maximum drawdown, annualized volatility/return and Sharpe calculations.
- Added normalized portfolio-versus-benchmark charts with selectable symbols.
- Added long-position risk sizing constrained by risk budget, paper cash and
  maximum allocation.
- Added simulation-only target-weight rebalancing with dollar/share estimates;
  no trades are placed by the simulator.
- Added explicit history-collection states instead of reconstructing unreliable
  performance before snapshot tracking existed.

## 0.9.0 - Orion AI v1.1

- Added SQLite-backed trade theses, invalidation prices and post-trade notes
  with inline journal editing.
- Added deterministic journal expectancy, payoff ratio, profit factor, win rate
  and streak statistics across the full trade history.
- Added Responses API chat streaming, incremental chat bubbles and cancellation;
  cancelled responses are not saved to Orion memory.
- Added offline prompt/answer quality fixtures and regression checks.
- Added per-component market-context caching with UTC freshness metadata,
  stale-on-error fallback and explicit partial-failure reporting.

## 0.8.1 - Local startup reliability

- Added `start-orion.ps1` for one-command Windows setup and startup.
- Added a network-free `/health` readiness endpoint and connected the frontend
  status indicator to it.
- Added backend and frontend tests for the health contract.

## v0.8.0 — Orion memory and intelligence tools

- Repaired and surfaced ticker-scoped SQLite conversation memory.
- Added saved Orion preferences and memory controls.
- Added daily briefing, opportunity scan and indicator explanations.
- Added persistent watchlist and hardened persistent paper trading.
- Added structured Orion stock-analysis responses.
- Fixed Orion route/body contracts, favorite removal and selected-ticker behavior.
- Added backend and frontend regression tests.

## v0.7.0

- Added stock analysis, Orion chat, chat bubbles, comparison and watchlist ranking.
- Added portfolio review, journal review and portfolio health score.
