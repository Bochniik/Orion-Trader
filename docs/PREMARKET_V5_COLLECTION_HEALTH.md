# Premarket V5 score-blind collection health

Added 2026-09-11 as the operational follow-up to the pre-registered early/mid/late cloud-shadow cadence.

## Purpose

Issue #3 ultimately requires leakage-safe proper-score and calibration evidence, but model-quality metrics should not be inspected while deciding whether the forward sample is operationally complete. `scripts/audit_premarket_v5_collection_health.py` therefore exposes collection coverage only.

The audit consumes immutable `premarket-v5-cloud-shadow-v2` prediction artifacts and verifies that each artifact:

- is `shadow_research_only` with order submission disabled;
- declares `causal_cutoff_enforced=true`;
- belongs to a real NYSE trading session rather than merely a Monday-Friday calendar date;
- belongs exactly to one pre-registered New York snapshot: 06:45 ET (`early`), 08:00 ET (`mid`), or 09:15 ET (`late`);
- uses exactly the frozen research universe `AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ` (ordering is irrelevant, membership is not);
- contains exactly one prediction row for every requested symbol;
- records the expected 5m, 15m, and 30m forecast objects for available symbols;
- does not duplicate the same session/snapshot pair inside one health report.

The fixed-universe check is intentionally independent of the artifact's own declaration. An artifact cannot make a substituted ticker appear protocol-valid merely by changing both its `symbols` list and its matching prediction row. This protects forward validation from silent universe drift while keeping the audit score-blind.

The trading-session check uses `scripts/nyse_session_calendar.py`, a deterministic standard-library implementation of recurring NYSE full-day closures including Good Friday, Juneteenth, observed Independence Day and the other regular exchange holidays. This avoids treating a weekday exchange holiday as one of the 55 distinct forward sessions required by Issue #3. One-off emergency closures are not guessed; they remain collection failures and must not silently increase validation readiness.

## Score-blind contract

The collection report uses contract `orion-premarket-v5-collection-health-v2` and always declares:

- `score_blind: true`
- `metrics_exposed: false`

The report contains only operational geometry: artifact/session counts, expected/observed/missing symbol-horizon pairs, coverage by early/mid/late snapshot, coverage by horizon, missing symbols, unavailable-data reasons, complete-artifact/session counts, a deterministic readiness gate, and a deterministic SHA-256 digest of the operational projection.

Probability, confidence, predicted return, direction, actionable state, realized outcome, Brier score, log loss, accuracy and ECE are intentionally excluded. Regression tests mutate those fields aggressively and require the health report to remain invariant at the readiness level.

## Validation readiness gate

Issue #3 uses a 40-session train + 10-session calibration + 5-session test walk-forward geometry. The health report therefore requires **55 complete distinct NYSE sessions independently for each preregistered snapshot** (`early`, `mid`, and `late`) before `ready_for_issue_3_score_inspection` may become true.

A session/snapshot observation is complete only when all expected pairs for the frozen protocol are present: 10 preregistered symbols × 3 supported horizons = 30 symbol-horizon forecast objects. A protocol-valid artifact with unavailable symbols or missing horizon forecasts remains visible in collection coverage and diagnostics, but it does **not** reduce the remaining complete-session count.

This prevents a subtle false-readiness case. For example, 55 raw `mid` session artifacts with one degraded session are reported as `distinct_session_count=55` but `complete_distinct_session_count=54`, so the `mid` regime remains not ready. A missing observation cannot be converted into validation maturity merely because a timestamped artifact exists.

The report exposes, per snapshot:

- observed distinct session count;
- complete distinct session count;
- required complete distinct session count (55);
- remaining complete distinct sessions;
- a boolean readiness state.

The overall readiness flag becomes true only when all three snapshot regimes satisfy the same frozen complete-session geometry. The gate remains score-blind: completeness depends only on the presence of the preregistered symbol-horizon observations, not on probabilities, realized outcomes, proper scores, accuracy, calibration or whether a forecast was favorable. Reaching readiness authorizes metric inspection for Issue #3; it does not imply model skill, acceptable calibration, or promotion eligibility.

## Evidence-health incident semantics

The integrated evidence-health report uses `orion-premarket-v5-evidence-health-v2`. It separates two concepts that must not be conflated:

- **historical operational incidents**: missing schedule delivery, unsuccessful workflow execution, missing artifact after a successful run, incomplete forecasts, or acquisition-ineligible artifacts;
- **structural evidence ambiguity**: duplicate scheduled delivery or a prediction artifact that cannot be matched unambiguously to the authenticated scheduled run population.

Historical operational incidents remain permanently visible in `status_counts`, `evidence_rows`, and `historical_incident_layers`. They are never erased or converted into successful observations, and they never contribute to the 55-complete-session minimum. However, an old operational miss no longer permanently poisons a cohort that later accumulates the full preregistered **55 complete, forward-eligible distinct sessions per snapshot**. This keeps the readiness gate consistent with the registered 40/10/5 count-based geometry instead of silently changing it into a stricter “zero operational incidents ever” rule.

Structural ambiguity remains fail-closed. `duplicate_delivery` and `unmatched_artifact` remain in `blocking_layers`, and `ready_for_issue_3_score_inspection` cannot become true until those conditions are resolved. The report exposes `historically_gap_free` as an operational diagnostic and `structurally_clean` as the provenance-integrity gate. The legacy `operationally_clean` field is retained as the historical gap-free diagnostic for existing consumers; it is not the v2 readiness predicate.

This change does not inspect or expose scores, authorize promotion, alter the frozen cadence or universe, modify model coefficients/features/thresholds/calibration, change risk policy, or enable order submission. It only prevents a historical infrastructure incident from redefining the preregistered sample-size policy after the fact.

## Evidence durability

Issue #3 requires at least 55 distinct sessions for the existing 40-session train + 10-session calibration + 5-session test walk-forward geometry. Eleven complete weeks contain exactly 55 weekdays, so a 30-day artifact window can never preserve the minimum forward sample long enough for that evaluation.

Premarket V5 cloud-shadow evidence therefore uses a 90-day artifact retention window. This covers the minimum 77-calendar-day weekday geometry and leaves limited slack for US market holidays, unavailable data, or missed/failed scheduled runs. `backend/tests/test_premarket_v5_evidence_retention.py` fails if the workflow silently regresses to a retention period shorter than this registered window.

Retention is an operational safeguard only. Extending evidence lifetime does not change the model, cadence, targets, thresholds, broker/feed configuration, or promotion policy, and it does not expose predictive scores while sample readiness is being assessed.

## Failure policy

The audit fails closed on off-cadence timestamps, weekends, recurring NYSE full-day market holidays, non-causal artifacts, duplicate session/snapshot artifacts, duplicate symbols, any missing/extra/substituted member of the frozen research universe, unexpected prediction tickers, missing prediction rows, or malformed available forecasts. Missing market data for an explicitly unavailable preregistered symbol is not fabricated; it reduces coverage, its reason is counted, and that session/snapshot is ineligible for the 55-complete-session readiness minimum.

The frozen-universe regression test includes the particularly dangerous case where the artifact keeps the same symbol count but substitutes one ticker and supplies a matching prediction for that substitute. That artifact must fail rather than contributing apparently complete coverage.

The snapshot resolver applies the same NYSE-session gate before dependency installation and market-data collection, so scheduled holiday cron events terminate as inactive `market_holiday` slots instead of consuming Alpaca calls or creating evidence that cannot count toward forward validation.

## Interpretation

Collection health is not model evidence. A coverage fraction of 1.0 means only that the intended forward observations were captured for the preregistered cadence and universe. It does not imply predictive skill and cannot promote Premarket V5.

Likewise, `ready_for_issue_3_score_inspection=true` means only that each preregistered snapshot has reached 55 complete NYSE sessions under the frozen walk-forward geometry and the accepted evidence population is structurally unambiguous. It is a permission to open the score-bearing evaluation, not a favorable model verdict.

The next logical step is to accumulate untouched early/mid/late artifacts and run this audit before opening any proper-score dashboard or settlement summary. Operational gaps may be investigated through score-blind coverage and unavailable-data reasons, but model outputs must remain hidden while deciding whether the sample is mature. Only after all three snapshot regimes reach 55 complete sessions should Issue #3 inspect Brier score, log loss, calibration, directional accuracy and fold/session stability. No outcome-driven cadence, universe or completeness-rule change is permitted under the existing pre-registration.
