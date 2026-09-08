# OrionTrader roadmap

## OrionTrader 2.0 — current direction

- [x] Milestone 1: repository audit, three-screen navigation, Today home,
  reusable Opportunity Card, simplified Analyze, preserved My Stocks data.
- [x] Deterministic presentation facade with stale-data, liquidity, conflict and
  risk/reward vetoes; no order capability in the core workflows.
- [ ] Browser/visual smoke gate in an environment with Chromium installed.
- [x] Milestone 2: one-action orchestration, bounded background training jobs,
  data/model readiness, strict promotion, cancellation and progress.
- [x] Immutable final-decision ledger and observed target/stop/excursion checks,
  with opt-in foreground monitoring and explicit missing-outcome limitations.
- [ ] Milestone 3: decision quality and measured outcomes — durable point-in-time
  capture, richer observation coverage and independent validation evidence.
- [ ] SaaS readiness: multi-worker state/lifecycle, provider entitlements,
  operational limits and deployment hardening. No subscriptions yet.

The older checklist below describes preserved prototype capabilities, not the
new primary UI or a promise that statistical models have demonstrated reliability.

## Foundation — complete

- [x] React dashboard and FastAPI backend
- [x] Search, live quotes, candles, news, favorites and watchlist
- [x] Paper trading, persistent positions and trade journal
- [x] Technical analysis and automated paper-trading bot

## Orion AI v1 — complete

- [x] GPT-backed stock analysis and chat
- [x] Chat bubbles and ticker-scoped SQLite memory
- [x] Saved risk, horizon and response-style preferences
- [x] Stock comparison and watchlist ranking
- [x] Portfolio and trading-journal review
- [x] Deterministic portfolio health score plus Orion explanation
- [x] Daily portfolio/watchlist briefing
- [x] Watchlist opportunity scan
- [x] Contextual RSI, SMA, EMA and volume explanations

## Orion AI v1.1 — complete

- [x] Add a Windows one-command launcher and network-free readiness endpoint
- [x] Add backend/frontend startup-contract smoke tests

- [x] Store structured trade theses, invalidation levels and post-trade notes
- [x] Add deterministic journal statistics (expectancy, payoff ratio, streaks)
- [x] Add AI response streaming and cancellation
- [x] Add prompt/evaluation fixtures for Orion answer quality
- [x] Cache market context with freshness metadata and partial-failure handling

## Portfolio intelligence

- [x] Sector and asset-class exposure
- [x] Drawdown, volatility and risk-adjusted performance metrics
- [x] Benchmark comparison and performance charts
- [x] Position-sizing and rebalancing simulator

## Strategy tooling

- [x] Backtesting engine
- [x] Strategy builder and saved strategies
- [x] Alerts for price, indicators, risk limits and thesis invalidation
- [x] Earnings calendar, analyst ratings and insider activity

## Platform

- [x] User accounts and per-user data isolation
- [x] Alpaca paper integration behind explicit safety controls
- [x] Portable Docker deployment and observability
- [x] Installable mobile PWA companion experience

## Broker-aware autonomous paper agent

- [x] Explicit Local Simulator / Alpaca Paper / Trading 212 Demo workspace source
- [x] Unified active-account portfolio, intelligence and Orion context
- [x] Alpaca tradable-universe discovery and market-wide candidate screening
- [x] Shadow, approval and bounded autonomous paper modes
- [x] Deterministic position, order, loss, spread, liquidity and frequency limits
- [x] Backend scheduler, proposal history and full audit trail
- [x] Runtime-off restart behavior and emergency kill switch
- [x] Independent operator gates for manual and autonomous paper submission

## Trading-terminal UX

- [x] URL-backed feature workspaces instead of a single scrolling page
- [x] Persistent desktop sidebar and mobile bottom navigation
- [x] Global ticker, account, broker and Orion-agent context
- [x] Pending-approval badge and globally available emergency stop
- [x] Lazy market panels and lightweight autonomy-status polling
- [x] Interactive OHLCV chart with crosshair, volume and trend overlays
- [x] Broker-first account summary when Alpaca Paper is connected
- [x] Searchable glossary and practical strategy playbooks

## Autonomous discovery v2

- [x] Balance most-active, gainer and loser live screeners
- [x] Rotate through the full active tradable Alpaca equity universe
- [x] Deprioritize recently reviewed symbols and track lifetime coverage
- [x] Diversify finalists by held positions, discovery, momentum and reversals
- [x] Separate neutral HOLD observations from rejected BUY/SELL orders
- [x] Explain action confidence, setup type and missing confirmation

## Research and execution UX

- [x] Detailed glossary mechanics, worked examples and strategy risk/exit plans
- [x] Day Trading, Swing Trading and Long-Term opportunity workspaces
- [x] News-aware structured candidate ranking and board-specific Orion follow-up
- [x] Two-step manual paper-order review without a typed confirmation phrase
- [x] Explicit New York/local chart time and stale-live-candle protection
- [x] Persistent per-user Day/Swing/Long-Term opportunity-board history

## Assistant-only product boundary

- [x] Keep Alpaca integration physically restricted to the Paper endpoint
- [x] Remove Live broker services, credentials, API routes and account UI
- [x] Keep real-money execution in a user-controlled external broker
- [x] Present a broker-neutral research-to-execution checklist
- [x] Add structural regression coverage proving Live routes are absent

## Risk-profile recommendation engine

- [x] Persist Conservative, Balanced and Aggressive modes per user
- [x] Keep every current recommendation unlevered at or below 1x
- [x] Disable borrowed exposure until realistic execution replay and date-split
      walk-forward validation pass
- [x] Calculate quantity from account risk, stop distance and slippage; cap
      notional exposure independently
- [x] Support optional manual USD-equivalent external planning capital
- [x] Save the risk profile, sizing source, audit gates and plan with each board
- [x] Keep setup quality distinct from probability of profit
- [x] Keep every recommendation research-only and externally executed

## Trading 212 connectivity

- [x] Add an official Trading 212 Demo account mirror
- [x] Show cash/value, positions, pending orders, historical orders,
      transactions and dividends with freshness/partial-failure metadata
- [x] Keep credentials per-user in backend memory and physically omit Live
      endpoints
- [x] Add Trading 212 Demo as a selectable active portfolio source
- [x] Feed the selected Demo portfolio into Orion reviews, health, chat,
      exposure, performance, sizing and rebalancing
- [x] Preserve broker currency and disclose estimated position allocation when
      the API omits account-currency position values
- [x] Add removable Opportunities history and audit-preserving Paper Lab clearing
- [x] Search exact broker instruments and support market, limit, stop and
      stop-limit Demo orders through fixed method/path allow-lists
- [x] Add independent server policy, short-lived review, atomic confirmation,
      cash/exposure/daily limits and duplicate protection
- [x] Reconcile broker states, recover uniquely matched unknown submissions,
      confirm cancellations and idempotently journal reconciled fills
- [x] Load the Trading 212 Demo tradable instrument universe into Opportunities
      with exact broker tickers, bounded rotation and broker-scoped coverage
- [x] Keep Trading 212 physically absent from autonomous execution; funded
      execution remains out of scope

## Opportunity intelligence v2

- [x] Calculate horizon-specific ATR, support, resistance, trend, momentum,
      relative volume, liquidity and volatility from OHLCV
- [x] Produce deterministic entry zones, breakout triggers, stops, targets and
      reward-to-risk plans whenever market structure is sufficient
- [x] Prefilter a larger finalist set with reproducible structure before bounded
      Orion news/profile/portfolio review
- [x] Blend deterministic and model evidence without treating setup quality as
      probability of profit
- [x] Distinguish confirmed, waiting, extended, below-standard,
      sizing-unavailable and data-insufficient states
- [x] Keep concrete levels visible for conditional setups and preserve the full
      score/gate audit in saved boards
- [x] Convert recommendation sizing through explicit FX evidence and fail
      closed without it
- [x] Add a current-quote Entry-ready scan with a complete deterministic
      readiness audit
- [x] Require Orion evidence review and the selected risk profile after
      technical readiness before marking a setup entry-ready
- [x] Persist scan intent and show explicit zero-match results without lowering
      standards

## Research strategy intelligence

- [x] Evaluate trend momentum and relative-strength pullback frameworks
- [x] Evaluate catalyst plus five-minute opening-range breakout structure
- [x] Evaluate regime-filtered mean reversion and volatility contraction
- [x] Add optional pairs divergence screening without claiming cointegration
- [x] Keep long-term diversified investing a portfolio process, not a chart buy
- [x] Detect and confirm Golden Crosses with 50/200-session SMAs
- [x] Present Death Crosses as defensive warnings, never automatic shorts
- [x] Publish entry, invalidation, target and reward/risk only for qualifying
      long setup states
- [x] Keep rule completion distinct from confidence and probability of profit
- [x] Add freshness-aware partial failure and explicit unavailable-data states

## Catalyst and breakout intelligence

- [x] Add bounded Catalyst Breakout Radar scans to Opportunities
- [x] Score float, volume trend, consolidation and ATR contraction
- [x] Score relative strength, mapped sector momentum and recent catalysts
- [x] Add timestamped-news and insider-purchase freshness requirements
- [x] Reserve only part of each scan for a starter catalyst watchlist while
      retaining rotating full-broker-universe discovery
- [x] Expose factor points, evidence coverage, microstructure and feed gaps
- [x] Keep readiness distinct from probability, entry approval and order intent
- [ ] Add licensed real-time SEC/press-release/FDA event ingestion with primary-
      source identifiers
- [ ] Add provider-backed options-flow and short-interest freshness metadata

## Explosive-Move Intelligence — v0.29 foundation complete

- [x] Add a separate Move Lab and preserve all existing workspaces
- [x] Keep PreMoveScore, IgnitionScore and DangerScore independent
- [x] Allow No Trade for danger, missing evidence, extension or failed breakout
- [x] Classify liquid large caps, liquid small caps, low-float momentum,
      biotechnology catalysts, recent IPOs and distressed/compliance risk
- [x] Apply category-specific watch, danger and exposure thresholds
- [x] Normalize timestamped Alpaca-news, corporate-action and SEC-filing events
- [x] Add declared-identity, cached and rate-limited SEC submissions metadata
- [x] Persist per-user scan history and audit-preserving public-event evidence
- [x] Add Adaptive Risk v1 with ATR stop, exposure, drawdown, liquidity,
      slippage and catastrophic-gap limits
- [x] Keep every probability target blank and labeled not calibrated
- [x] Keep the complete feature research/shadow-only with no order route

## Explosive-Move Intelligence — v0.30 streaming complete

- [x] Add explicit per-user Alpaca market/news WebSocket sessions
- [x] Authenticate and subscribe to a bounded candidate list without wildcard
      market subscriptions
- [x] Add reconnect/backoff, fatal entitlement handling and sequence cursors
- [x] Add channel health, freshness, error and backpressure observability
- [x] Keep market evidence bounded in memory and persist normalized public news
- [x] Use fresh streamed evidence in scans with snapshot fallback
- [x] Stop streams on operator stop, logout, broker disconnect and shutdown
- [x] Keep stream ingestion physically separate from every order path

## Explosive-Move Intelligence — v0.31 replay complete

- [x] Add a separate Extreme-Mover Replay Lab for 20%, 50% and 100% outcomes
- [x] Freeze OHLCV preparation features at each historical decision close
- [x] Isolate all future bars in a separate configurable outcome window
- [x] Audit outcome paths, drawdowns, false positives and missed extreme moves
- [x] De-duplicate displayed extreme examples while retaining all observations
- [x] Add score-band and chronological 70/30 descriptive comparisons
- [x] Persist full replay audits per user with summary-first history loading
- [x] Disclose adjusted-history, overlap, survivorship and missing-event limits
- [x] Keep probabilities null and replay physically separate from order routes

## Explosive-Move Intelligence — v0.32 execution stress complete

- [x] Add a separate professional Execution Lab beside live and replay modes
- [x] Model spread, slippage/impact, adverse gaps and liquidity participation
- [x] Model capacity-limited partial fills and limit-price no-fill outcomes
- [x] Model LULD-style interruption and broker/venue rejection as blocked states
- [x] Stress protective-stop fills and report risk expansion
- [x] Expose formula, assumption, regulatory and missing-data audits
- [x] Persist full simulations per user with summary-first history loading
- [x] Add cutoff-safe Replay Lab to Execution Lab handoff
- [x] Keep scenario probabilities null and all broker/order routes absent

## Explosive-Move Intelligence — validation phases next

- [ ] Full filing-content, press-release, FDA and exchange-notice ingestion with
      primary-source identifiers and explicit redistribution/licensing review
- [ ] Historical point-in-time dataset retaining delisted/failed securities
- [x] Assumption-driven bid/ask, partial-fill, LULD-style, gap, rejection and
      slippage simulator (official historical NBBO/halt replay remains absent)
- [ ] PRE-MOVE WATCH and IGNITION ALERT queues with deduplication and cooldowns
- [ ] Logistic-regression baseline with date-split walk-forward evaluation
- [ ] Probability calibration and regime/category performance reports
- [ ] Portfolio weekly loss, correlated exposure and close-only survival controls
- [ ] Paper-only validation deployment; no funded autonomous execution

## Orion Predictive Intelligence v1

- [x] Phase 1: bounded liquidity ranking with average/current dollar volume,
      time-adjusted relative volume, spread, trade frequency, volume rates,
      volatility, batch-relative percentile and Tier A-D
- [x] Phase 1: per-user SQLite run history, provenance, coverage, partial
      failures, Tier A priority and progressively stronger future lower-tier
      evidence gates
- [x] Phase 1: keep all probabilities null, deterministic and independent from
      LLM calculations and every order path
- [x] Phase 2: real-time rolling feature buffers with extensible feature schema
- [x] Phase 3: leakage-controlled multi-horizon UP/DOWN/NEUTRAL dataset
- [x] Phase 4: walk-forward interpretable models and out-of-sample calibration
- [x] Phase 5: execution-cost-aware long/short expected value
- [x] Phase 6: composite OrionOpportunityScore after validated components exist
- [x] Phase 7: deterministic market-regime classification
- [x] Phase 8: Orion Live Edge frontend with liquid and higher-risk sections
- [x] Phase 9: explicit NO TRADE — NO STATISTICAL EDGE gates
- [x] Phase 10: prediction/outcome laboratory with Brier, calibration and
      after-cost simulated performance
- [x] Phase 11: Orion AI explanation of immutable deterministic results only

## Orion Learning Brain v1

- [x] User-selected single-stock Live Edge analysis
- [x] Broad liquidity-first discovery before finalist analysis
- [x] Tier A/B research visibility even when the verdict is NO TRADE
- [x] Fourteen-family mathematical strategy consensus with unavailable states
- [x] Per-user good/bad settled-outcome memory
- [x] Bayesian shrinkage and bounded learned strategy weights
- [x] Adverse-pattern veto without probability mutation
- [x] BUY/SELL/HOLD research interpretation with no order route
- [ ] Retrain probability artifacts only after a separately validated,
      versioned walk-forward promotion workflow exists

## Professional reliability — next

- [ ] Alpaca Paper order-state reconciliation and partial-fill journal handling
- [ ] Durable background job queue for scans and alerts
- [ ] Provider provenance, quote-age badges and Alpaca/yfinance reconciliation
- [ ] Encrypted Paper-credential vault for managed deployments
- [ ] Horizon-specific outcome tracking and confidence calibration
- [ ] External-account currency conversion and instrument-specific cost models
- [ ] Backup/restore workflow, error reporting and operator health dashboard
