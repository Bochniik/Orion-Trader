# Regular-hours V3.1 forward validation protocol

Pre-registered: 2026-09-12. This document freezes the first score-inspection gate before Regular-hours V3.1 forward outcomes are used to evaluate or tune the model.

## Purpose

Regular-hours V3.1 now produces immutable, provenance-audited shadow artifacts during the US cash session. The next methodological risk is optional stopping: inspecting Brier score, log loss or directional accuracy after only a handful of favorable sessions and then changing the model, thresholds or calibration in response.

This protocol prevents that. Collection health remains score-blind until the minimum complete-session gate is satisfied.

## Frozen collection universe

The standard forward-validation universe is:

AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ.

Custom-universe artifacts remain operationally visible but do not count toward the standard forward-session gate.

A complete standard session is defined by the existing collection-health contract: every standard-universe observation collected for that NYSE date must be available and timestamp-provenance-valid, with zero provider/runtime failures and zero provenance gaps. If any standard artifact for the date is incomplete, the entire date is incomplete for the gate.

## Score-inspection gate

Predictive-score inspection is locked until at least **30 complete standard NYSE sessions** have accumulated under the provenance-valid V2+ cloud-shadow contract.

Before 30 complete sessions:

- do not inspect or publish aggregate Brier score or log loss for the forward sample;
- do not inspect aggregate directional accuracy or calibration buckets;
- do not tune probabilities, thresholds, calibration, horizon policy, cadence or symbol selection based on realized forward outcomes;
- operational audits may inspect availability, provenance coverage, retries, failures, schedule delivery and session completeness only.

The machine-readable collection-health report exposes the threshold, remaining complete sessions and `ready_for_score_inspection`, but derives those fields only from score-blind operational data.

## Metrics after the gate

Once 30 complete sessions exist, the first score-bearing report should include at minimum:

- Brier score by 30m / 1h / 3h / 5h horizon;
- binary log loss by horizon;
- directional accuracy as a secondary descriptive metric;
- calibration / expected calibration error and probability buckets;
- coverage and suppression rate;
- results by symbol and pooled across the preregistered universe;
- session-block uncertainty or bootstrap intervals so correlated forecasts within one trading day are not treated as independent samples;
- comparison against simple no-skill probability baselines and any already-frozen incumbent/challenger output available on exactly paired timestamps.

Missing or sparse cells must be reported as insufficient evidence rather than pooled selectively.

## Promotion policy

Reaching 30 complete sessions authorizes **inspection only**. It does not authorize promotion, live trading, automatic order submission, leverage changes or risk-policy changes.

Any future promotion rule must be separately preregistered before using the forward scores to choose its thresholds. `promotion_authorized` therefore remains false in the collection-health contract.

## Change control

The 30-session threshold must not be moved because early results look unusually good or bad. A future protocol may supersede this one for a documented methodological reason, but it must receive a new protocol identity before the affected forward outcomes are inspected.

Changes required solely to restore data integrity or collection reliability are allowed, but sessions collected under materially different predictive logic should not be silently pooled as one untouched validation sample.

## Next step

Continue collecting score-blind Regular-hours V3.1 evidence. If provenance or scheduler reliability remains poor, fix the collection mechanism first. Once the gate reaches 30 complete sessions, build a separate score-bearing evaluator that consumes settled outcomes without modifying the frozen shadow artifacts.