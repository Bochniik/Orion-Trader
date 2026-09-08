# OrionTrader audit report

## 2.0 Milestone 2 audit (current, 2026-09-02)

Implemented bounded one-action preparation and analysis, immutable final
decisions and saved-plan observation checks. Hardened chronological label
purging, completed-bar availability, independent feature freshness and candidate
promotion before enabling automatic preparation. Existing account/data/assistant
boundaries remain. No funded execution, new AI request, paid data subscription
or destructive migration was introduced.

Important limits: single-process worker lifecycle, cooperative cancellation,
limited historical quote/plan-outcome coverage, foreground-only monitoring,
and no browser visual verification without Chromium. Full current contracts
and verification are in `docs/MILESTONE_2.md` and `CHECK_REPORT.txt`.

## 2.0 Milestone 1 audit (historical)

See `docs/ORIONTRADER_2_ARCHITECTURE.md` for the complete keep/refactor/deprecate
matrix. Key findings: a 3,944-line route composition module, overlapping scanner
workflows, technical rule scores presented as confidence, no automatic model
lifecycle, limited IEX coverage, request-time rather than source-time quote
metadata, and mixed Vite 8/Vitest 4 JSX runtimes. The new core addresses the UI
and presentation boundaries while preserving the underlying systems. Broad
model/data redesign and multi-worker SaaS hardening are deferred.

No paid AI or live broker requests were made for validation. No live trades were
placed. The browser binary was unavailable and download timed out; visual and
browser-interaction assertions remain unverified. Historical findings below
belong to previous releases and should not be read as a fresh validation claim.

## Scope

Reviewed the full FastAPI service layer, SQLite schema and access patterns,
React component tree, API client, package manifests, Git history and project
documentation. External OpenAI and live market calls are isolated behind mocks
in automated tests; no paid AI calls or live paper trades are made by the suite.

## Confirmed issues fixed

| Severity | Finding | Resolution |
| --- | --- | --- |
| Critical | The uploaded ZIP was truncated inside `node_modules` and had no central directory. | Recovered every complete source/Git entry with size and CRC checks, restored tracked frontend files from the embedded Git commit, and rebuilt dependencies from the lockfile. |
| High | `orion_ai_service` raised at import time without an API key, disabling every backend route. | OpenAI client creation is lazy; only AI calls fail with a clear 503. |
| High | Frontend stock analysis called `/orion-ai/{ticker}` while the backend exposes `/orion-ai/analysis/{ticker}`. | API client now matches the unambiguous backend route. |
| High | Portfolio review sent no required JSON body and returned 422. | AI action helpers send a memory scope; compatible backend bodies are optional. |
| High | Persisted memory was never loaded into chat bubbles and could not be cleared in the UI. | Memory restores on ticker selection, exposes stats/preferences, and has a clear action. |
| High | A second `removeFromWatchlist` function silently overrode the API-backed implementation. | Removed the duplicate and retained persistent server removal. |
| High | Realized P&L was summed from only the latest 200 trades. | SQL now aggregates the full journal while returning a bounded recent list. |
| Medium | Paper trades could race across multiple server workers sharing cash/positions. | Writes use WAL, busy timeouts and `BEGIN IMMEDIATE` transactions. |
| Medium | Watchlist state reset on backend restart. | Watchlist now persists in SQLite. |
| Medium | Typing in search changed the active ticker and triggered quote/news/AI requests for partial symbols. | Search text and active ticker are separate states. |
| Medium | Comparison detection treated arbitrary short uppercase words as stock symbols. | Comparison dispatch now requires explicit `compare`, `vs`, or `versus` syntax. |
| Medium | RSI and moving averages could produce NaN/errors on flat or short history. | Analysis validates columns and handles short/flat series deterministically. |
| Medium | AI stock JSON was prompt-only and could be malformed. | Responses API parsing now uses a Pydantic schema. |
| Low | News timestamps were dropped before reaching Orion prompts. | Context now carries `published_at`. |
| Low | Runtime dependencies were split inconsistently across two requirement files. | Runtime and dev requirements are explicit and reproducible. |
| Low | Windows startup required several manual commands and failed unclearly when dependencies were absent. | A root launcher now checks prerequisites, installs missing dependencies, starts both services and waits on a network-free health endpoint. |
| High | Local simulator controls and analytics remained active after Alpaca connected, creating two conflicting portfolio views. | Added an explicit active source and normalized Alpaca Paper holdings across portfolio, intelligence and Orion context. |
| High | Giving AI direct broker access could bypass sizing and operational safeguards. | AI can create proposals only; deterministic risk code owns sizing, validation and the separately gated paper execution call. |
| Medium | The chart lacked volume, exact crosshair values and useful trend overlays. | Added validated OHLCV data, period statistics, pan/zoom and toggleable SMA/EMA overlays. |
| Medium | Local simulator starting cash remained visually prominent after Alpaca connected. | Alpaca now becomes the active workspace on connection and Overview leads with synchronized broker equity and buying power. |
| High | Autonomous cycles repeatedly selected from only most-active stocks and gainers, making a real 13,000-symbol universe look hardcoded. | Added losers, rotating full-universe discovery, recent-symbol deprioritization, diverse finalists and persistent coverage reporting. |
| Medium | Every HOLD was labeled `risk_rejected`, conflating a neutral wait decision with a failed order. | HOLD now records `observed_hold`; only BUY/SELL proposals can fail deterministic execution checks. |
| Medium | Intraday candle timestamps could be interpreted using the server or browser timezone and stale quotes could create misleading current-time candles. | Naive provider bars are localized to New York before UTC serialization, display zones are explicit, and stale live intervals are not synthesized. |
| Medium | A typed confirmation phrase made manual paper orders cumbersome without adding an independent security boundary. | Replaced it with a visible two-step order review while retaining the disabled-by-default server gate and explicit confirmed request field. |
| Medium | General opportunity scanning did not distinguish evidence appropriate for day, swing and long-term decisions. | Added separate structured horizon boards with bounded candidates, news context, confirmation, invalidation, limitations and research-only follow-up. |
| High | Horizon research supplied held positions first, so owned symbols could dominate what was intended to be independent market discovery. | Opportunities now disables held-position priority, broadens live/rotating discovery and exposes the exact coverage/source boundary. Automation retains held-position review for risk monitoring. |
| Medium | Crosshair time used the selected timezone but visible Lightweight Charts axis ticks still used the library default. | Added and tested an explicit timezone-aware tick formatter and reapplied it with the New York/local selector. |
| Medium | Opportunity recommendations existed only in React component state and disappeared when users opened Automation or refreshed. | Successful boards are now immutable per-user SQLite snapshots with a restoreable history UI. |
| Critical | A Live-account surface—even read-only—blurred OrionTrader's assistant-only boundary and invited future funded-account coupling. | Removed the Live service, credentials, configuration, routes and UI. A structural regression test proves the old route family is absent. |
| High | Letting an AI confidence number directly select leverage could turn an uncalibrated model judgment into excessive exposure. | Setup quality is explicitly not probability; deterministic code independently gates instrument eligibility, quantity, exposure and leverage. |
| High | Using Alpaca Paper's default $100,000 balance for planned external trades could produce dangerously irrelevant quantities. | Added optional per-user USD-equivalent external planning equity/cash and records the exact sizing source on every saved board. |
| Medium | Optional CFD guidance could hide which condition allowed leverage. | Every plan persists and displays pass/fail gates for horizon, quality, reward-to-risk, spread, liquidity, daily movement and freshness. |
| Low | The growing single JavaScript bundle crossed the production warning threshold. | Lazy-loaded the heaviest workspaces into independent chunks and reduced the initial bundle. |
| Critical | Reintroducing a generic broker client could silently restore a funded-order path after the assistant-only redesign. | Trading 212 is fixed to the Demo host. Separate internal allow-lists expose only documented reads, four Demo order types and numeric-ID cancellation; the Live host and environment switch remain physically absent. |
| High | Broker credentials in `.env` would be shared across Orion users and persist on disk. | Trading 212 Demo credentials are isolated by authenticated user in backend memory and are removed on disconnect/restart. |
| High | Treating a foreign security's quoted price as the account currency would corrupt allocation and risk calculations. | Position values prefer provider account values; otherwise they are allocated from Trading 212's account-currency invested total and explicitly marked estimated. |
| Critical | Making Trading 212 an active Orion context could accidentally couple it to autonomous order execution. | Manual Demo execution is isolated behind its own review service and policy. No Trading 212 method is referenced by the autonomous manager or risk guardian, no autonomous Trading 212 route exists, and Paper Agent still requires Alpaca Paper independently. |
| Critical | Two simultaneous confirmation requests could submit the same reviewed Demo order twice. | Final validation is followed by an atomic compare-and-set from `reviewed` to `submitting`; only one request can claim a review. A second request fails closed. |
| High | A timeout after an order request creates an ambiguous broker outcome where retrying may duplicate the order. | Orion records `submission_unknown`, never retries, and reconciliation assigns an order ID only when exactly one recent broker order matches ticker, side, quantity, prices and time. |
| High | Comparing an instrument's USD price directly with EUR account limits would understate or overstate risk. | Review fetches instrument currency and a current account/quote-currency FX rate, converts estimated notional into account currency, and fails closed when currency evidence is unavailable. |
| High | Persisting Trading 212 credentials would widen the impact of local database or ZIP exposure. | Credentials remain isolated per authenticated user in process memory. Only review state, broker IDs, audit metadata and reconciled Demo fills are stored in the user's SQLite database. |
| Medium | Deleting Paper Lab history could destroy evidence needed to explain or reconcile automated-paper actions. | Clear advances per-user visibility cutoffs only; underlying proposal/event audit rows remain intact and the action requires the agent to be Off with no pending approvals. |
| Low | Opportunity-board history had no cleanup path and could grow indefinitely. | Added confirmed deletion by horizon or across all boards with per-user database scoping. |
| High | Opportunities could use only Alpaca's universe even when Trading 212 Demo was the selected account. | Added an explicit broker-universe selector, cached Trading 212 instrument metadata, exact broker-ticker preservation and bounded independent quote screening. |
| High | Treating a broker directory as an instruction to quote or deeply analyze every instrument could create provider fan-out, latency and cost failures. | Each source uses deterministic per-user rotation, a 160-instrument screening ceiling, up to 16 OHLCV finalists and at most eight deep Orion classifications. |
| High | A Trading 212 instrument price could be sized directly against a different account currency. | Cross-currency recommendation sizing uses an explicit current FX rate and fails closed as sizing-unavailable when conversion evidence is missing; the research levels remain visible. |
| High | Opportunity levels were optional language-model outputs, so Orion frequently returned null prices and the UI reduced distinct causes to “plan incomplete.” | Added deterministic horizon-specific OHLCV structure that produces entry, breakout, stop and target levels whenever data is sufficient, plus explicit trigger/retest/quality/sizing/data states. |
| High | An uncalibrated model score could dominate candidate ordering even when chart structure was weak or unavailable. | Final rank now blends preserved deterministic and model scores; missing or weak structure caps the verdict and cannot become a Strong Candidate. |
| Medium | Candidate finalists were selected mainly from absolute movement and liquidity before horizon evidence was calculated. | Each rotating scan now evaluates a larger finalist set with horizon-specific trend, momentum, volume, volatility and structure before the strongest bounded evidence reaches Orion. |
| Medium | Optional news/profile outages and account-currency mismatches both erased otherwise useful technical plans. | Critical OHLCV quality is gated separately from optional context; concrete levels remain visible, and quantity uses an explicit FX conversion or fails closed as sizing-unavailable. |
| High | Fixed slippage in backtests could make an apparently strong setup look executable even when spreads widened, liquidity thinned, price gapped, trading paused or a broker rejected the order. | Added a separate deterministic Execution Stress Lab with visible scenario capacity, partial fills, limit no-fills, stop-gap expansion, rejection and LULD-style blocking; it does not alter strategy signals. |
| High | A synthetic pause model could be mistaken for an official historical LULD reconstruction. | The response and UI state that official bands require live reference-price/quote state; no NBBO, depth, pause tape, venue queue or reopening fill is claimed. Paused scenarios return no immediate fill and unknown cost. |
| Medium | Historical replay examples required manual retyping before execution stress, increasing transcription error. | Added a one-click handoff carrying only the cutoff-safe anchor close and prior 20-session average volume into a separate unsent hypothetical plan. |
| Critical | Asking GPT to generate short-horizon market probabilities would make stochastic prose look mathematically authoritative and allow values to drift between identical inputs. | Every probability is produced by the deterministic calibrated model service. Orion receives immutable downstream evidence only, has no numeric output fields, and attempted numeric restatement is rejected. Predictive routes have no order adapter. |
| High | Including today's still-forming daily candle in an average-volume baseline would leak current target-session information and distort relative volume. | Daily history is treated as session labels; the current New York session is removed before all preceding-session metrics, with a regression test covering timezone-naive indexes. |
| High | Sparse or partially failed market evidence could create a deceptively high liquidity tier if unavailable values were silently filled. | Missing values remain null, earn zero points, lower evidence coverage and fail closed; history-based factors require at least ten completed sessions. |
| Medium | Ranking only most-active names would repeatedly surface the same stocks and leave the claimed broker universe unexamined. | Each bounded pass blends live activity leaders with deterministic per-user rotating exploration and reports exact provider-universe and sampled counts. |

## Remaining engineering risks

- Authentication and physical per-user databases are now present, but public
  deployment still requires HTTPS, controlled registration, backups, rate
  limiting at the reverse proxy and routine dependency/security maintenance.
- Market requests are synchronous. Context calls are now cached with stale
  fallback, but a cold multi-stock request can still be delayed by a provider.
- Portfolio health is a transparent heuristic, not a complete risk model; it
  now includes companion volatility, sector and drawdown reporting, but beta,
  factor exposure and tax-aware rebalancing are not yet modeled.
- Historical portfolio metrics begin with v0.10 daily snapshots; pre-upgrade
  performance is intentionally not reconstructed from incomplete price data.
- Paper fills use the latest quote without slippage, fees, order states or market
  hours. They are simulations, not execution-quality estimates.
- Strategy backtests model configurable fixed basis-point friction but not
  borrow costs, dividends, splits, liquidity, partial fills or tax effects.
- Execution Lab improves deterministic stress visibility but is assumption-
  driven. It does not have historical NBBO/depth, queue priority, venue routing,
  official LULD/halt tapes or opening/reopening auction data and therefore must
  not be treated as a fill forecast or regulatory replay.
- Alerts are evaluated only while the local frontend is open; they are not a
  durable background notification service.
- Alpaca credentials are deliberately memory-only, so users reconnect after a
  backend restart. A future secrets-vault integration would be required for
  durable broker credentials without weakening the current storage boundary.
- Trading 212 Demo credentials remain memory-only, while manually confirmed
  Demo execution is available behind a disabled-by-default server flag. Public
  API shapes and rate limits can evolve, so fixed contracts, partial-feed
  reporting and offline tests still require periodic verification against the
  official documentation. Estimated position allocation and reference/FX
  quotes are safeguards, not broker-native execution guarantees.
- The autonomous scheduler is intentionally single-process and memory-only. It
  restarts Off, requires credentials to be reconnected, and is not a durable
  distributed job system.
- Market-wide screening depends on the selected broker directory and independent
  market-data uptime. Trading 212 exchange mappings are intentionally explicit;
  unsupported instruments and quote gaps are reported rather than guessed.
  Candidate-level failures are isolated, and live-provider behavior is not
  asserted by the offline automated suite.
- Opportunity-board ranking quality depends on the bounded provider snapshot.
  It now has deterministic market-structure components and hybrid ranking, but
  it is not exhaustive research, does not currently track subsequent outcomes
  by horizon and must not be interpreted as calibrated probability or advice.
- External CFD plans cannot see the user's actual broker state, available
  instruments, margin health, financing, tax position or fills. Planning capital
  is manual USD-equivalent input and must be kept current by the user.
- Stop orders cannot guarantee the stop price during gaps or fast markets.
  Slippage allowances are estimates rather than execution guarantees.
- Real-money execution is deliberately out of product scope. OrionTrader
  supports research and Paper validation only; funded orders remain
  user-controlled actions in an external regulated broker.
- Predictive Intelligence now calculates experimental calibrated probabilities,
  expected value and opportunity rankings, but this is not evidence of a durable
  market edge. Alpaca IEX snapshots may understate consolidated activity;
  yfinance intraday history is adjusted research data rather than point-in-time
  institutional data; depth, queue position, routing, fees, borrow, halts and
  executable fills remain unmodeled. One-minute bars cannot support the
  thirty-second horizon. A horizon remains NO TRADE until its untouched holdout,
  walk-forward, calibration and after-cost gates pass, and live laboratory
  reporting remains provisional before 500 settled predictions.
- Live Edge now ranks a materially broader discovery batch and sorts by
  absolute LiquidityScore inside each risk section. A selected ticker is pinned
  for analysis, while Tier A/B NO TRADE research remains visible before Tier
  C/D audit rows.
- Fourteen deterministic strategy families contribute an auditable consensus.
  Their output is not a probability. Settled outcomes update per-user,
  Bayesian-shrunk strategy weights only within a bounded range; sufficiently
  adverse comparable memory can veto a decision, while positive memory cannot
  bypass any existing hard gate.
