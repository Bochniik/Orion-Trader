# OrionTrader 2.0 — Milestone 1: Simplified Core Experience

Historical Milestone 1 audit. Milestone 2 is now implemented; its current
contracts and remaining limits are in [MILESTONE_2.md](MILESTONE_2.md).
The three-screen product structure below remains authoritative.

## Product contract

Open Orion and understand what deserves attention within ten seconds. There are
only three primary destinations: **Today**, **Analyze**, and **My Stocks**.
Conclusions come first; evidence and operational detail are opt-in. No screen
submits orders. This is a first milestone, not the completed 2.0 vision.

## Audit of the v0.35 prototype

The source archive contains a React 19/Vite application, a FastAPI backend, 35
service modules, per-user SQLite stores, and Python/Vitest regression suites.
There is no Git metadata in this supplied working copy; no branch or commit is
manufactured. Preserve the canonical repository when integrating this release.

| Area | Finding | Milestone decision |
| --- | --- | --- |
| Frontend shell | `main.jsx` mixes navigation, search, quote/news polling, portfolio, broker and agent state; ten primary workspaces | Replace shell with three workflows; keep authentication root separate |
| Navigation | Hash-based, ten destinations | Three destinations; map old bookmarks to the appropriate core workflow |
| Market data/search | yfinance histories, quotes, news, search, batch loaders; request timestamp is not an exchange quote timestamp | Preserve APIs; label snapshot freshness honestly; never infer live freshness from fetch time |
| Charts | lightweight-charts, ranges, overlays, timezone and quote updating | Preserve in Analyze, mounted on demand |
| Basic analysis | Additive SMA/EMA/RSI score named `confidence_score` | Preserve legacy API; never expose it as probability in 2.0 |
| Strategy research | Nine playbooks with check-level evidence and explicit missing inputs | Reuse as technical context, not as calibrated trade permission |
| Predictive pipeline | Rolling features, chronological datasets, two baselines, calibration, EV, regime, 14-family consensus and no-trade gates | Reuse only available saved models; add conservative presentation gates and max-five distinct ticker selection |
| Liquidity | Absolute dollar-volume/spread/activity score, Tier A–D, bounded 60–100 sampling; IEX can undercount consolidated activity | Preserve; Today admits only A/B, A first; no low-liquidity fallback to fill the page |
| Model lifecycle | Explicit synchronous train endpoint, five-day one-minute training batches, no job queue or automatic model promotion | Hide manual lab controls; report unavailable when a saved validated model is absent. Automatic training is the next milestone |
| Scanner | Multiple overlapping scanner APIs; full-universe rotation is bounded, not an instantaneous whole-market scan | Reuse Live Edge under a small core facade; disclose sample coverage |
| News/catalysts | yfinance, Alpaca snapshot/stream, SEC metadata behind configured contact, keyword rules | Preserve; evidence only; no new verified real-time feed claims |
| AI | Several free-text/structured paths; predictive explanation has immutable numeric boundary | Reuse only constrained predictive explanation in core cards; no LLM calculation or automatic paid AI call |
| Memory | Conversation/preferences, predictions, outcomes, and bounded outcome-based learning are separate stores | Preserve all data; do not imply chatting trains a price model |
| Watchlist | Per-user SQLite, add/remove; quote updates | Preserve, no browser-global replacement or destructive migration |
| Portfolio | Source-aware local/paper/demo snapshots, journal, analytics | Preserve read/display and journal access under My Stocks; remove account-value tiles from home |
| Alerts | Persisted rules, explicit check endpoint; no continuous general monitor | Surface real checked exceptions, distinguish unchecked/error/quiet; never claim continuous monitoring |
| Auth | Cookie sessions, CSRF for writes, password hashing, request-scoped user databases | Preserve; new routes inherit middleware and per-user stores |
| Alpaca / Trading 212 | Fixed paper/demo hosts; optional guarded paper/demo submission; no live-money adapter | Connections in a secondary data/settings panel; no order UI or agent controls in core workflows; legacy endpoints remain isolated compatibility APIs |
| Replay / execution / strategies / learning screens | Useful isolated research tools, not a coherent daily workflow | Retain source, services, tests and APIs; remove from primary navigation and production import graph |
| Tests/deployment | pytest, Vitest (mostly server rendering), offline quality evals, launcher, Docker, PWA | Keep suites, add facade and interaction regression checks; no subscriptions or hosting changes |

## Architecture in this milestone

`CoreApp` owns only navigation, selected ticker, session-level UI state and data
connections. Today, Analyze and My Stocks load only the data each screen needs.
`OpportunityCard` renders one structured backend decision without computing
probabilities. `decision_engine.py` is a pure, deterministic normalization and
eligibility boundary. `core_routes.py` is the small compatibility facade over
existing services; it does not duplicate model training or import order services.

The existing route module is approximately 3,944 lines. The new facade still
depends on this legacy composition root; extracting service providers and route
groups gradually is safer than rewriting tested features during a UI milestone.

Decision fields include ticker, company name (nullable), evidence timestamp,
decision/direction, confidence (nullable calibrated probability), entry zone,
invalidation, targets, conservative risk/reward, expected move, horizon,
liquidity, setup quality, regime, reasons, warnings and original model outputs.
Technical evidence alone returns WAIT. A trade card requires validated model
permission, current input timestamps, A/B liquidity, known positive after-cost
EV, coherent levels, adequate risk/reward and no opposing actionable horizon.
Fetching a stale observation now does not make it current. Empty scans, failed
scans and unconfigured scans are different states. Counts refer to the sampled
universe, not the entire market.

## Recommendation history foundation

Existing Live Edge scans already persist immutable feature/probability/level
snapshots with prediction IDs and measurable later outcomes. Core decisions
retain these IDs and original outputs. A later recommendation ledger should
store the *final* gated decision (including vetoes), immutable model/version,
data/source timestamps, entry/stop/target, rationale and origin. Separate outcome
rows must record target/stop ordering uncertainty, MFE/MAE, costs and horizon
expiration; they must never rewrite the original recommendation. Do not treat
prediction-direction accuracy as target-hit rate or achieved trading P&L.

## Deferred, explicitly unavailable

- Automatic training/retraining, data entitlement selection and model promotion.
- Calibrated confidence for pure technical analysis or a missing model.
- Automatic recommendation/thesis monitoring, entry/target/stop notifications.
- Unified event-level outcome ledger and demonstrated strategy reliability.
- New indicator families, SaaS multi-worker lifecycle, subscriptions/payments.

## Next exact milestone

**Milestone 2 — One-action decision orchestration.** Add bounded background jobs
for dataset readiness and training/validation, explicit model freshness and
promotion gates, source-specific freshness for every feature, a final-decision
ledger, and outcome-based monitoring for saved plans. Analyze becomes a single
job with progress and cancellation; Today uses the same final-decision contract.
No manual baseline controls, silent training loops, or fabricated opportunities.
