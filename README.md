# OrionTrader 2.4

Milestone 4 adds a liquidity-first Opportunity Radar, structured directional confidence, staged automatic refresh, and the guarded Orion Prime alert state. Release archives use the `OrionTrader-2.4.zip` naming scheme; future upgrades increment the second number (`2.5`, `2.6`, …).

## Milestone 2 — One-action Decision Orchestration

**What deserves my attention in the market right now, and why?**

OrionTrader is a local-first research assistant with three primary screens.
The application does not execute live trades. One action now handles bounded
preparation, statistical validation and current analysis. Missing or failed
evidence still returns WAIT; installed software is not proof of predictive edge.

| Screen | What it does now |
| --- | --- |
| **Today** (home) | At most five distinct Tier A/B setups, ordered by liquidity. Opening checks existing models; clicking Refresh also prepares a baseline if needed. Empty, incomplete, unavailable and market-closed states are distinct. |
| **Analyze** | Enter a ticker. Orion checks readiness, prepares/validates a bounded baseline when necessary, and returns one final verdict. Progress and Cancel are available; no manual model controls. |
| **My Stocks** | Watchlist, positions and journals, plus saved decision plans, observed level/outcome checks and recent decision history. Optional checks every minute while this screen is open. |

Use **Data & account** for research connections, selecting the displayed portfolio
and signing out. No baseline-building, model-selection or order controls are in
the main interface. Old bookmarks redirect to the relevant new workflow.

## Start / update on Windows

1. Close the running OrionTrader frontend and backend.
2. Back up your existing project, especially `backend/data` and `backend/.env`.
3. Copy this release's source over the existing project. Keep your existing
   `backend/data` and `.env`; the release deliberately contains neither.
4. Run `Start-OrionTrader.cmd` or `powershell -ExecutionPolicy Bypass -File .\start-orion.ps1`.
5. Sign in with the existing account. Refresh the browser if an old tab is open.

Do not delete user databases during an upgrade. There is no destructive schema
migration in this milestone. A fresh folder needs your previous data copied in
to retain accounts, watchlists, portfolios and memory.

The established Python/Node setup, launcher, Docker and PWA assets are preserved.
See [the prototype reference](docs/PROTOTYPE_REFERENCE.md) for existing deployment
configuration; its old navigation and lab instructions are historical.

## Honest limits

- Technical research works without an Alpaca connection when the market provider
  responds. A technical rule score is **not** probability or trade permission.
- Current statistical decisions require Alpaca research data and a saved model
  with a validated, current horizon. Analyze and explicit Today Refresh can
  prepare one automatically. If validation fails, Today reports **unavailable**,
  and Analyze returns **WAIT** with available technical context.
- Preparation uses at most four Tier A/B symbols from an 80-symbol sample,
  five days of completed minute bars, at most 6,000 samples per horizon and
  existing deterministic estimators. No low-liquidity training fallback.
- Attempts are limited to once per six hours per user, including failed or
  cancelled attempts. There are no silent training loops. A first analysis can
  take several minutes and may still fail the quality gates.
- Older baselines must pass the new purged, cross-symbol validation contract.
  Failed candidates never replace the incumbent model. Model/data age ceilings
  are seven/four days, respectively; these are policy limits, not accuracy claims.
- Today evaluates a bounded, rotating universe sample, not every stock at once.
- Quotes/features must be timestamped and current; cards expire to WAIT. Company
  names, confidence and levels are not fabricated when unavailable.
- Confidence describes calibrated direction, not probability of hitting the
  displayed ATR-derived target. Short/AVOID is bearish research, not an order.
- Existing news/catalyst, memory, replay, strategy and simulation services and
  stored records remain intact. Most specialist screens are no longer in the
  primary interface. Browser-local legacy favorites are untouched; migration
  into the per-user watchlist is deferred.
- Save an unexpired qualified result with **Save plan to monitor**. Check it
  under My Stocks. Saving a ticker alone does not create a plan. Opt-in periodic
  checks run only while My Stocks is open and visible; they stop on navigation,
  logout or closure. There are no push notifications or unattended monitoring.
- Plans report observed levels and exact-horizon reference outcomes when data
  exists. Missing bars, boundary fragments and same-bar stop/target ambiguity
  are explicit. No fills, target-hit probability or achieved P&L are invented.
- Jobs have a five-minute publication deadline and two global worker slots,
  one per user. Cancellation is cooperative: an in-flight provider/CPU stage
  may finish later, but cannot publish a new final decision after cancellation.
  Interrupted jobs are not silently resumed. This runner requires ONE backend
  process; multi-worker SaaS deployment is not supported yet.
- Legacy paper/demo endpoints remain isolated compatibility APIs, with their
  existing fixed hosts and submission switches. The new workflows cannot call
  them. No live-money trading adapter or subscription billing is added.


## OurAI Forward Evidence (optional research integration)

The OurAI V3 bridge is opt-in, read-only and limited to research evidence about the **absolute magnitude** of a 15-minute price movement. It does **not** predict direction, authorize a trade, place orders, or enable automatic live trading. Do not interpret its magnitude estimate as a BUY/SELL signal or as a directional probability.

For a **transitional, explicit opt-in launch** from a trusted local OurAI checkout, stop any running Orion/OurAI servers and run from the Orion root:

```powershell
.\\start-orion.ps1 -SkipInstall -StartOurAI -OurAIPath "C:\\Users\\<you>\\Desktop\\OurAI"
```

This starts the existing OurAI read-only server from its own `.venv`, enables the Orion client only in the spawned backend environment, and then starts Orion. It requires the trusted OurAI checkout and verified forward journal to be present. Port 8765 must be free. The launcher waits for a valid verified-journal response and fails closed before starting Orion if OurAI is unavailable. In opt-in mode it runs Uvicorn without the reload supervisor and Vite directly through Node rather than npm, so startup rollback can terminate the primary processes it created; the default development launch remains unchanged. This is **not yet an embedded distribution**. The opt-in launcher supervises the three processes it starts: when a managed process exits or the launcher terminates normally, it attempts to stop only its own OurAI, backend and frontend processes. Unrelated pre-existing listeners must be left alone. Synthetic Windows lifecycle tests pass; full application end-to-end and descendant-process cleanup still require verification. Default launcher behavior remains unchanged, disabled and safe. Do not use this option for remote or untrusted folders.

When the bridge returns `status: unavailable`, its bounded `unavailable_reason` separates `upstream_timeout` (local read/connect/write/pool deadline), `upstream_connection_failure` (local transport/protocol error), `upstream_http_failure` (HTTP error), and `invalid_upstream_evidence` (failed verification or malformed payload). None of these is a model accuracy metric or a trading signal. DNS `getaddrinfo` or WinError 10060 in a separate shadow market-data collector is a **data-provider outage**, not proof of a bad prediction; the Orion bridge itself contacts only numeric loopback `127.0.0.1` and does not diagnose external market-provider connectivity.

The Orion Intelligence evidence panel remains disabled unless a trusted single-user local machine runs the OurAI loopback process and the Orion backend explicitly sets `OURAI_BRIDGE_ENABLED=true`. Passing cloud CI tests does not start that local process or enable the bridge. Keep this integration local and do not expose the loopback endpoint publicly.

## Architecture and verification

The [2.0 architecture audit](docs/ORIONTRADER_2_ARCHITECTURE.md) records what was
preserved, refactored and removed from primary navigation, the decision contract,
known limitations and the recommendation-history design. The exact current
contracts are in [Milestone 2](docs/MILESTONE_2.md).

```sh
# Backend, using the project's environment
python -m pytest backend/tests -q
python backend/evals/run_startup_smoke.py

# From frontend/
npm test
npm run build
```

`frontend/e2e/core-smoke.cjs` is a production-browser test with deterministic HTTP
fixtures. It requires an installed Playwright package and Chromium. Run after
`npm run build`; it never calls market providers or places trades. If Playwright
is installed outside the project, set `ORION_PLAYWRIGHT_MODULE` to its package
path. The current sandbox could not download Chromium, so browser/visual checks
are **not claimed as passed**. See `CHECK_REPORT.txt` for completed checks.

Next: **Milestone 3 — Decision quality and measured outcomes**: durable
point-in-time observation capture, richer outcome coverage, regime-aware
validation and clear evidence of whether the recommendations actually help.
Do not add more primary screens or relax quality gates to fill Today.
