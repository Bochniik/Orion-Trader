# Milestone 2 — One-action decision orchestration

Version `2.0.0-m2`, 2026-09-02. Builds on the three-screen Milestone 1.

## User workflow

Analyze starts a bounded authenticated job. It checks the model and data,
prepares a baseline if necessary, validates a candidate, evaluates current
evidence and saves the final verdict. Progress labels describe actual stages,
not a fake completion percentage. Cancel suppresses later result publication.
Today uses the same decision adapter; manual Refresh permits preparation but
opening Today alone does not train. No model controls, AI call or order path
were added to the primary workflow.

## Components and contracts

| Component | Responsibility |
| --- | --- |
| `core_jobs.py` | Two bounded daemon worker slots, one per user; same-request deduplication; cooperative cancellation; 300-second publication deadline; failed/interrupted receipts |
| `core_readiness.py` | Model age, observed-data age, validation evidence, completed-bar availability and per-feature provenance |
| `core_orchestration.py` | At most one preparation attempt per six hours; four liquid symbols; candidate-only save; validated promotion |
| `core_store.py` | Per-user job receipts, immutable final decisions, separate saved-plan configuration and append-only observation checks |
| `plan_monitor.py` | Observed entry/invalidation/target states and exact-horizon reference outcomes; no simulated fills |
| `core_routes.py` | Authenticated job, history and plan API plus retained synchronous compatibility facade |
| `coreJobClient.js` | Polls job state, bounded busy retries, cancellation after navigation/start-response races or polling failure |
| `SavedPlans.jsx` | On-demand checks, optional foreground one-minute checks, history without presenting old decisions as current |

The legacy route composition root remains. Workers copy request-scoped service
context, retaining the user identity but not the HTTP request/cookies/headers.
Existing auth/CSRF and per-user database isolation remain authoritative. Logout,
broker disconnect and shutdown request cancellation. A worker slot stays occupied
until its in-flight stage actually exits. Restart marks unfinished receipts
interrupted when that user's database is next accessed; it does not restart work.

This is an explicitly **single-backend-process** desktop runner, not a distributed
queue. Multiple Uvicorn workers are unsupported: a later hosted milestone needs
cross-process leases, job ownership, backpressure and durable provider credentials
designed for that deployment. FastAPI's [background-task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/)
also distinguishes local task handling from heavier distributed processing.

## Validation tightened before automation

The earlier chronological split could leave training target windows overlapping
the calibration or test period. New baselines purge those windows across all
symbols, keep identical timestamp groups on one side, and end all walk-forward
folds before the final holdout. Partition outcome boundaries are saved for audit.
This follows time-series ordering rather than random splits; see the
[official cross-validation guidance](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split).

Targets must span the stated number of seconds. Missing minutes and overnight
gaps no longer become nominal one-/five-/thirty-minute labels. Provider bar-start
timestamps become bar-close availability times and incomplete bars are excluded
from the new core pipeline. Old artifacts remain stored but cannot satisfy the
new `purged-cross-symbol-v2` gate merely by retaining a reliable flag.

Promotion independently checks saved boundaries, at least 500 final holdout
observations, three separated walk-forward folds, Brier < 0.65, ECE <= 0.10,
accuracy >= majority baseline, and positive simulated after-cost edge. These
minimum research gates are not proof of robust profitability or independent
sample size. Observations overlap within segments, the sample is small and
survivorship/provider limitations remain. No cross-market reliability claim.

Training uses a fixed, disclosed 5 bps spread stress assumption; it does not
retroactively label today's quote as historical bid/ask evidence. Current trade
eligibility still requires timestamped quotes and cost-aware upstream EV gates.
No 30-second training data is fabricated from one-minute bars.

## Freshness

Every registered feature has source, as-of time, maximum age and availability.
Stale fields are nulled before model inference. Stock and SPY references are
checked separately; a fresh quote cannot refresh an old benchmark or minute bar.
Benchmark forward alignment is limited to one minute. Sector features remain
unavailable when no sector history exists. Quote timestamps are retained from
actual quote events, not the newest trade. Undated stream events are rejected;
trade and aggregate-bar volumes are not double-counted. Required stock and
benchmark inputs must be fresh again at the final publication boundary.

## Final decisions and observations

Final decisions include vetoed WAIT observations from Today as well as Analyze
results. The original payload, model ID/version, feature provenance, levels,
warnings, origin and SHA-256 digest are retained. Displayed cards reference those
IDs. Later checks never rewrite them; the existing prediction/outcome learning
store is preserved and is not falsely relabeled as a new self-training brain.

At most 20 plans may be enabled. Stopping a plan disables checks without deleting
its decision or observations. Current prices require a genuine fresh trade
timestamp. Completed minute bars can establish that a level was observed, but
not an executable fill. If both levels occur in one bar, ordering is unknown.
Only full intervals inside the plan count; boundary fragments are excluded.
Exact-horizon close data is required for a fixed-horizon outcome; the next
session's price is never substituted. Observed excursions cover only available
bars and are not total-path or achievable-return guarantees.

The optional frontend monitor checks at most once per minute on the visible
My Stocks screen. It does not survive leaving that screen, closing the browser,
logout or disconnect. Checks are snapshots and may miss intervening events.
No email/push notification or always-on monitoring claim is made.

## Next milestone

Milestone 3 should improve measured decision quality: durable point-in-time
capture, sufficient independent validation periods, richer plan outcome
coverage and regime-aware reliability reporting. Preserve the three workflows,
do not lower thresholds to force recommendations, and do not add subscriptions
or autonomous execution before the evidence and deployment foundations exist.
