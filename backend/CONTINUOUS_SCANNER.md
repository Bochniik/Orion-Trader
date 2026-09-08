# Task 5A2 — continuous staged market scanning

Version 3.2 adds deterministic day/swing/long-term research plans and a separate
forward-observation journal; see `../RELEASE-3.2.md`. The historical description
below applies to the original directional-candidate path. The new research path
does persist immutable setup evidence and separate hypothetical outcomes. It does
not change directional prediction records, model training, or their settlement.
Research feature snapshots now appear inside research plans, never credentials.

The 3.1 closed-session runtime path and installation notes are documented in
`../RELEASE-3.1.md`. Historical market categories now load even on a cold start
outside regular hours; they are separate from live snapshots and Orion Picks.

Task 5A2 wraps the Task 5A1 staged scanner in a small, lifecycle-managed
research service. It continuously refreshes bounded market pages and a much
smaller active-candidate set while preserving the existing staged formulas,
model, calibration, risk gates, and no-order boundary.

## Service boundary

The service is `app.services.continuous_scanner.ScannerScheduler`. It receives
an existing `ExistingScannerRunner`, a `ScannerStateStore`, a per-user broker
connection predicate, and `ScannerSettings`. It calls the existing one-shot
`StagedMarketScanner`; it does not train a model, create predictions, write
settlement records, call an LLM, send alerts, or prepare/submit orders.

The production runner in `scanner_runtime.py` reuses the configured Alpaca
client for the active/tradable universe, IEX snapshots and clock, and the
existing Yahoo feature path. Credentials remain in the existing broker client;
the scanner state contains no credentials or feature vectors.

## Cadence and bounded work

Defaults are intentionally conservative:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `ORION_SCANNER_ENABLED` | `true` | Enable lifecycle loop |
| `ORION_SCANNER_BROAD_INTERVAL_SECONDS` | `600` | Minimum interval for a new universe page |
| `ORION_SCANNER_ACTIVE_INTERVAL_SECONDS` | `120` | Refresh interval for active candidates |
| `ORION_SCANNER_MINIMUM_CYCLE_GAP_SECONDS` | `60` | Hard spacing between expensive scans |
| `ORION_SCANNER_PAGE_SIZE` | `250` | Symbols considered per broad page |
| `ORION_SCANNER_ACTIVITY_LIMIT` | `100` | Activity finalists |
| `ORION_SCANNER_FAST_LIMIT` | `30` | Fast-score finalists |
| `ORION_SCANNER_FULL_ANALYSIS_LIMIT` | `15` | Full model analyses |
| `ORION_SCANNER_RESULT_LIMIT` | `10` | Rows retained in the public snapshot |
| `ORION_SCANNER_ACTIVE_LIMIT` | `50` | Maximum active candidates |
| `ORION_SCANNER_ACTIVE_TTL_SECONDS` | `1800` | Maximum age of an active candidate |
| `ORION_SCANNER_INACTIVE_CYCLES` | `3` | Fully successful misses before removal |

Provider/cache safety settings are also centralized in `ScannerSettings`:
feature ideal/max ages are 120/1,200 seconds, snapshots expire after five
minutes, history is cached in bounded 10-symbol provider chunks, and requests
are spaced by one second. The service rejects unsafe settings (for example,
active cadence below 60 seconds or a page above the staged scanner's ceiling).

## Lifecycle and invocation

`main.py` creates one scheduler using the existing application data root. The
FastAPI lifespan starts its daemon loop after the existing broker/settlement
services and stops it cooperatively before shutdown. A connected user's scanner
is activated after login recovery and after Alpaca connect; it is cancelled on
disconnect and logout. Activation restores the persisted cursor/state, but the
first broad refresh is scheduled immediately and the first active refresh waits
for the active cadence unless an active set is already present.

For deterministic/manual operation, call the service directly:

```python
scheduler.run_scan_cycle(user_id, mode="broad", now=fixed_now)
scheduler.run_scan_cycle(user_id, mode="active", now=fixed_now)
scheduler.run_due_once(now=fixed_now)
```

`run_due_once` runs at most one bounded cycle (broad takes priority when both
are due). The public API is read-only:

```text
GET /scanner/current
```

Authentication determines the user; a query-string user id is ignored. The
endpoint never triggers provider work and returns a structured current-state
document.

## Broad rotation

Each broad cycle obtains the connected broker's normalized active/tradable
universe, fingerprints it, and scans one alphabetically ordered page. The
cursor is persisted as `next_offset`; after the final page the next cycle wraps
to page zero and records `last_full_rotation`. A changed universe fingerprint
resets the cursor safely. The service never claims that Alpaca's active-assets
response is a complete listing of every US security.

The scan remains staged: quality and liquidity filters run before activity,
fast score, and full directional analysis. A page may return no candidates;
thresholds are not relaxed. If a provider failure or cancellation makes the
page incomplete, the prior good snapshot and cursor are preserved and the
failure is visible.

## Active candidates

Only symbols selected by a successful broad result enter the active set. Each
entry contains bounded identity/score metadata, `entered_at`, `last_seen_at`,
`last_scanned_at`, and an inactive-cycle counter; it never stores model feature
vectors or probabilities. Active refreshes scan only this set, so they do not
re-run broad-universe screening.

An entry expires after 1,800 seconds by default or after three fully successful
refresh misses. Provider failures do not count as misses. The active set is
bounded by 50 and is pruned before each cycle and when the state is read.

## Current state and restart behavior

`ScannerStateStore` uses one SQLite table, `scanner_current_state`, keyed by
user id. It stores one JSON document containing:

- `snapshot`: most recent bounded candidates, mode, generated time and provider metadata;
- `previous_snapshot`: prior successful snapshot for continuity;
- `last_successful_scan`, `last_attempt_at`, `failure` and cycle diagnostics;
- `active`: bounded active-candidate lifecycle metadata;
- `universe`: total count, page/cursor, pages completed, fingerprint and rotation markers;
- `next_broad_at`, `next_active_at` and `next_allowed_at` scheduling timestamps.

On restart, state is recovered from SQLite and the cursor/active metadata are
available immediately. A recovered snapshot is never presented as current: its
candidate freshness is recomputed from its timestamps, and its overall state is
`stale` or `partial_failure` until a new successful scan. Corrupt/unreadable
state fails closed to an empty diagnostic state rather than preventing broker
activation.

## Freshness and delayed Yahoo data

The endpoint exposes `freshness` on every candidate and at the top level. The
states are:

| State | Meaning |
| --- | --- |
| `current` | Price and technical features are inside the ideal ages (normally 120s) |
| `delayed` | Evidence is usable for research but older than ideal and inside 1,200s |
| `stale` | Evidence exceeds the technical ceiling or snapshot TTL |
| `unavailable` | Required timestamp/quality evidence is missing or invalid |

The current provider path uses Alpaca IEX snapshots and delayed Yahoo minute
features. Delayed evidence is labeled and receives a linearly increasing
display penalty up to the configured 10 points; it is not relabeled as live.
Stale/unavailable rows are excluded from `top_candidates` and may appear under
`last_known_candidates`. `trade_permission_current` also requires the original
decision's actionability and current freshness. These fields are research
status, not an execution authorization.

## Concurrency, errors and rate protection

Only one expensive cycle runs in the process at a time. A per-user cancellation
event and a global non-blocking cycle lock prevent overlapping scans, including
manual calls racing the background loop. Provider/cache checkpoints stop work
between bounded calls. One failed symbol or provider batch is recorded in
diagnostics while unrelated candidates continue where possible.

The cache keeps a bounded copy of assets and historical daily/minute frames;
current snapshots are deliberately not cached. Logical provider requests are
chunked and spaced. A provider exception leaves the last successful snapshot
visible with an explicit failure/stale status and does not advance the rotation
cursor. Recovery on the next due pass clears the failure and publishes a new
snapshot. Nothing in this service is an order or alert route.

## Deterministic example

The following is a synthetic test fixture, not a live recommendation:

```json
{
  "status": "ready",
  "scan_mode": "broad",
  "scanner_running": false,
  "freshness": {"state": "delayed", "ideal_age_seconds": 120,
                 "maximum_age_seconds": 1200},
  "universe": {"total_symbols": 5, "current_page": 1,
               "pages_completed": 1, "next_offset": 2},
  "active_candidate_count": 2,
  "top_candidates": [{"ticker": "AAA", "model_direction": "UP",
                       "final_decision": "NO_TRADE",
                       "eligible_for_current": false}]
}
```

The explicit `NO_TRADE` and freshness fields demonstrate that ranking a symbol
does not authorize a trade. A delayed or stale result remains auditable rather
than being promoted by a fallback.

## Request/model budget and limitations

For a cold-cache default broad page of 250 symbols, the expected logical calls
are approximately: one Alpaca asset call, one clock call, three 100/100/50
snapshot calls, 25 ten-symbol daily-history batches, and 11 ten-symbol minute
history batches (the finalist set plus SPY). The default model budget is at
most 15 full analyses for the configured one `5m` horizon. These are logical
client calls; yfinance may issue more underlying HTTP requests. Warm caches
reduce history calls, while active refreshes avoid broad-universe calls.

With an approximately 4,300-symbol universe, 250-symbol pages require roughly
18 broad cycles (about three hours at the default ten-minute cadence), plus
processing time. This is deliberately bounded rather than an instantaneous
claim of full-market coverage. Yahoo's delayed/cross-source volume and minute
history remain the main data-quality limitations. Market lists, alerts,
multi-provider routing, model training/evaluation and Opportunity Radar are
outside Task 5A2 and remain future milestones.

## Validation

The Task 5A2 deterministic suite covers lifecycle start/stop and disablement,
page rotation and wrap, universe changes, active entry/expiry/refresh, cadence,
overlap/cancellation, provider failure/recovery, empty/partial scans, state
restart and storage errors, delayed/stale projections, API authentication and
connection hooks, cache chunking/spacing and reuse, and reduced model-call
budgets. Tests use synthetic providers and fixed clocks; no network or real
credentials are required.
# 3.0 activation correction

Authenticated registration, login and browser-session restoration now perform
the same network-free activation check. Repeated session restoration does not
cancel a running scan, recreate its runner or reset pagination. An explicit
Alpaca reconnect replaces the runner/cache. Successful activation wakes the
existing worker and queues the first broad page immediately, subject to the
existing minimum provider-cycle spacing. Scanner GET endpoints remain read-only.

Provider configuration and market-session state are separate. The current
production adapter requires per-user Alpaca Paper credentials for active/tradable
assets, IEX timestamped snapshots and the market clock. Yahoo supplies delayed
daily/minute history and the existing previous-close fallback; it has no
standalone universe/current-snapshot scanner adapter. Trading 212 portfolio
connectivity is not this scanner's market feed. No new fallback feed was added.

Credentials are intentionally memory-only: after a backend restart, reconnect
in Data & account. An app login cookie or an OpenAI key does not restore Alpaca
credentials. There is no automatic Alpaca credential environment import.
`provider_availability` now exposes exact configuration/capability reasons,
independently of market-open checks. Disabled scanning, missing credentials,
missing history client, pending first scan, inactive session, closed market and
unverified market clock are distinct. Safe HTTP 401/403/429 diagnostics expose
rejected credentials, entitlement denial and rate limiting without API bodies.

When closed, an existing snapshot is retained as stale. With no snapshot, TODAY
shows MARKET CLOSED rather than claiming no source is connected. Last-session
market-intelligence observations can be read only as stale last-known results,
with both current and observation session dates disclosed. No timestamps,
probabilities or stale observations are renewed. New tests exercise authenticated
session restore -> production runner -> existing Yahoo/Alpaca transports (mocked)
-> persisted state -> read-only endpoints, without a model or invented candidates.
