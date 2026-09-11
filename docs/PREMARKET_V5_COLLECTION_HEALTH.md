# Premarket V5 score-blind collection health

Added 2026-09-11 as the operational follow-up to the pre-registered early/mid/late cloud-shadow cadence.

## Purpose

Issue #3 ultimately requires leakage-safe proper-score and calibration evidence, but model-quality metrics should not be inspected while deciding whether the forward sample is operationally complete. `scripts/audit_premarket_v5_collection_health.py` therefore exposes collection coverage only.

The audit consumes immutable `premarket-v5-cloud-shadow-v2` prediction artifacts and verifies that each artifact:

- is `shadow_research_only` with order submission disabled;
- declares `causal_cutoff_enforced=true`;
- belongs exactly to one pre-registered New York snapshot: 06:45 ET (`early`), 08:00 ET (`mid`), or 09:15 ET (`late`);
- uses exactly the frozen research universe `AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ` (ordering is irrelevant, membership is not);
- contains exactly one prediction row for every requested symbol;
- records the expected 5m, 15m, and 30m forecast objects for available symbols;
- does not duplicate the same session/snapshot pair inside one health report.

The fixed-universe check is intentionally independent of the artifact's own declaration. An artifact cannot make a substituted ticker appear protocol-valid merely by changing both its `symbols` list and its matching prediction row. This protects forward validation from silent universe drift while keeping the audit score-blind.

## Score-blind contract

The generated report uses contract `orion-premarket-v5-collection-health-v1` and always declares:

- `score_blind: true`
- `metrics_exposed: false`

The report contains only operational geometry: artifact/session counts, expected/observed/missing symbol-horizon pairs, coverage by early/mid/late snapshot, coverage by horizon, missing symbols, unavailable-data reasons, and a deterministic SHA-256 digest of the operational projection.

Probability, confidence, predicted return, direction, actionable state, realized outcome, Brier score, log loss, accuracy and ECE are intentionally excluded. Regression tests mutate those fields aggressively and require the health report to remain byte-equivalent at the data-structure level.

## Evidence durability

Issue #3 requires at least 55 distinct sessions for the existing 40-session train + 10-session calibration + 5-session test walk-forward geometry. Eleven complete weeks contain exactly 55 weekdays, so a 30-day artifact window can never preserve the minimum forward sample long enough for that evaluation.

Premarket V5 cloud-shadow evidence therefore uses a 90-day artifact retention window. This covers the minimum 77-calendar-day weekday geometry and leaves limited slack for US market holidays, unavailable data, or missed/failed scheduled runs. `backend/tests/test_premarket_v5_evidence_retention.py` fails if the workflow silently regresses to a retention period shorter than this registered window.

Retention is an operational safeguard only. Extending evidence lifetime does not change the model, cadence, targets, thresholds, broker/feed configuration, or promotion policy, and it does not expose predictive scores while sample readiness is being assessed.

## Failure policy

The audit fails closed on off-cadence timestamps, weekend artifacts, non-causal artifacts, duplicate session/snapshot artifacts, duplicate symbols, any missing/extra/substituted member of the frozen research universe, unexpected prediction tickers, missing prediction rows, or malformed available forecasts. Missing market data for an explicitly unavailable preregistered symbol is not fabricated; it reduces coverage and its reason is counted.

The frozen-universe regression test includes the particularly dangerous case where the artifact keeps the same symbol count but substitutes one ticker and supplies a matching prediction for that substitute. That artifact must fail rather than contributing apparently complete coverage.

## Interpretation

Collection health is not model evidence. A coverage fraction of 1.0 means only that the intended forward observations were captured for the preregistered cadence and universe. It does not imply predictive skill and cannot promote Premarket V5.

The next logical step is to accumulate untouched early/mid/late artifacts and run this audit before opening any proper-score dashboard or settlement summary. Only after regime/horizon cells have adequate forward coverage should Issue #3 inspect Brier score, log loss, calibration, directional accuracy and fold/session stability. No outcome-driven cadence or universe change is permitted under the existing pre-registration.
