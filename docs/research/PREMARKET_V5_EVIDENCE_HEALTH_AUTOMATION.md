# Premarket V5 automated evidence health

Issue #3 requires a real point-in-time forward cohort before predictive scores may be inspected. The score-blind evidence-health audit therefore runs independently of Brier score, log loss, calibration, directional accuracy, confidence, realized labels, or any promotion decision.

## Production evidence source

The authoritative forward source is `.github/workflows/premarket-v5-cloud-shadow.yml`. Its decision-grade acquisition contract was completed after the 2026-09-11 trading session, so `2026-09-14` is frozen as the first eligible evidence session. Earlier artifacts remain diagnostic only and must not be backfilled into the decision cohort.

The workflow retains immutable prediction artifacts for 90 days. This exceeds the preregistered 55-session geometry (40 train + 10 calibration + 5 untouched test) while providing slack for holidays and occasional operational failures.

## Automated score-blind audit

`.github/workflows/premarket-v5-evidence-health.yml` runs on weekdays after the latest possible 09:15 ET snapshot has passed its acquisition-maturity window. It has only `contents: read` and `actions: read` permissions.

`scripts/collect_premarket_v5_actions_evidence.py` reads the actual scheduled workflow-run metadata from GitHub Actions, downloads only the matching live Premarket V5 artifact for each successful run, safely parses the ZIP, and requires the prediction payload to be bound to the same `github_run_id`. Expired artifacts are not silently accepted. Ambiguous artifacts, unsafe archive paths, malformed JSON, or run-ID substitution fail closed.

The GitHub artifact-download endpoint is treated as a GitHub REST API redirect endpoint, not as a raw binary endpoint. The authenticated API request uses GitHub's JSON media type (`application/vnd.github+json`) and API-version header; GitHub then redirects to the temporary archive URL. The redirect handler strips the bearer token whenever the target host changes, while the downloaded bytes still pass the existing ZIP/path/provenance validation before use. This contract is regression-tested because an `application/octet-stream` request caused the first scheduled evidence-health run on 2026-09-14 (`34890249929`) to fail with HTTP 415 before any score-blind report could be produced.

The collector intentionally keeps only score-blind delivery metadata. It does not request or calculate outcomes or model-quality metrics. The collected inputs are passed to `scripts/audit_premarket_v5_horizon_evidence_health.py`, which attributes mature slots to delivery, workflow execution, artifact persistence, forecast completeness, acquisition eligibility, and horizon-specific decision-grade completion.

The resulting report and its score-blind input summary are retained for 90 days. A red or blocked evidence-health state is an operational/research-readiness signal only; it does not change the runtime model, calibration, thresholds, risk rules, market-data feed, broker integration, or order path.

## Fail-closed score-inspection gate

Cohort maturity alone is not sufficient to unlock Issue #3 model-score inspection. The unified evidence-health report may mark `ready_for_issue_3_score_inspection=true` only when both conditions hold:

1. every early/mid/late cohort has the preregistered number of prospective decision-grade forward sessions for every required horizon; and
2. the delivery-to-artifact chain is operationally clean for every mature expected slot.

Duplicate scheduled deliveries and prediction artifacts that cannot be matched to the exact mature scheduled run are explicit blocking layers. They cannot be masked by having enough otherwise valid artifacts. Horizon-specific acquisition timing also cannot be masked by a globally healthy artifact: a delayed recovery observation may remain prospective for 15m/30m while being ineligible for 5m. This keeps the transition from score-blind collection to Brier/log-loss/calibration inspection fail closed.

## Interpretation

Before the 55-session early/mid/late geometry is complete, the correct action is to repair the first non-zero operational blocking layer and continue forward collection. Predictive metrics must remain uninspected. Once every preregistered cohort is mature, every mature expected slot is decision-grade complete for each required horizon, and there are no duplicate deliveries or unmatched artifacts, Issue #3 may proceed to the already bound event-nested validation and research-gate path.
