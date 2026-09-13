# Premarket V5 automated evidence health

Issue #3 requires a real point-in-time forward cohort before predictive scores may be inspected. The score-blind evidence-health audit therefore runs independently of Brier score, log loss, calibration, directional accuracy, confidence, realized labels, or any promotion decision.

## Production evidence source

The authoritative forward source is `.github/workflows/premarket-v5-cloud-shadow.yml`. Its decision-grade acquisition contract was completed after the 2026-09-11 trading session, so `2026-09-14` is frozen as the first eligible evidence session. Earlier artifacts remain diagnostic only and must not be backfilled into the decision cohort.

The workflow retains immutable prediction artifacts for 90 days. This exceeds the preregistered 55-session geometry (40 train + 10 calibration + 5 untouched test) while providing slack for holidays and occasional operational failures.

## Automated score-blind audit

`.github/workflows/premarket-v5-evidence-health.yml` runs on weekdays after the latest possible 09:15 ET snapshot has passed its acquisition-maturity window. It has only `contents: read` and `actions: read` permissions.

`scripts/collect_premarket_v5_actions_evidence.py` reads the actual scheduled workflow-run metadata from GitHub Actions, downloads only the matching live Premarket V5 artifact for each successful run, safely parses the ZIP, and requires the prediction payload to be bound to the same `github_run_id`. Expired artifacts are not silently accepted. Ambiguous artifacts, unsafe archive paths, malformed JSON, or run-ID substitution fail closed.

The collector intentionally keeps only score-blind delivery metadata. It does not request or calculate outcomes or model-quality metrics. The collected inputs are passed to `scripts/audit_premarket_v5_evidence_health.py`, which attributes mature slots to delivery, workflow execution, artifact persistence, forecast completeness, acquisition eligibility, or decision-grade completion.

The resulting report and its score-blind input summary are retained for 90 days. A red or blocked evidence-health state is an operational/research-readiness signal only; it does not change the runtime model, calibration, thresholds, risk rules, market-data feed, broker integration, or order path.

## Interpretation

Before the 55-session early/mid/late geometry is complete, the correct action is to repair the first non-zero operational blocking layer and continue forward collection. Predictive metrics must remain uninspected. Once every preregistered cohort is mature and decision-grade, Issue #3 may proceed to the already bound event-nested validation and research-gate path.
