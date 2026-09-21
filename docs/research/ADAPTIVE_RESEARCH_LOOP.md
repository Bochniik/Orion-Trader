# Adaptive Research Loop

Orion's adaptive research loop is deliberately separated from runtime trading behavior.

## Purpose

Settled point-in-time evidence should shorten the path to better hypotheses without allowing the current model to tune itself on the same observations used to judge it. The first stage therefore mines failure patterns from the immutable cloud-shadow evidence ledger and produces research hypotheses only.

The diagnostic contract is `orion-adaptive-research-diagnostics-v1`.

## Stage 1 — settled-error diagnostics

`backend/evals/adaptive_research_error_diagnostics.py` reads the append-only cloud-shadow evidence ledger and reports horizon baselines plus direction, confidence-band, symbol and reliability-profile slices. A candidate failure pattern needs minimum observation/session coverage, material excess error and a Wilson 95% lower bound above the same-horizon baseline.

These are diagnostics, not model-selection results. A reported pattern can be caused by noise, correlated slices, market-regime concentration or a weak incumbent. It is a hypothesis worth testing, not a rule to deploy.

## Stage 2 — immutable challenger registry

`backend/evals/adaptive_challenger_registry.py` freezes the protocol boundary before a challenger can collect approval evidence. Every evidence-informed candidate records:

- its hypothesis and exact change summary;
- the last development-evidence cutoff that was allowed to influence its design;
- a strictly later forward cutoff;
- code SHA and optional model-artifact SHA-256;
- the horizons being tested;
- the frozen evaluation-protocol contract and thresholds.

The canonical candidate material is hashed into an immutable SHA-256 and deterministic candidate ID. Mutating any registered hypothesis, cutoff, lineage or protocol field fails integrity validation. Registration after the declared forward cutoff also fails closed.

`assert_forward_evidence_eligible` rejects empty evidence, malformed timestamps, observations at or before the candidate's forward cutoff, and horizons outside the preregistered set. This makes the development/approval split machine-checkable rather than a documentation convention.

## Stage 3 — registered tournament gate

`backend/evals/registered_challenger_tournament.py` is the mandatory adapter for evidence-informed adaptive candidates entering the paired intraday tournament. It validates the immutable registration before scoring, requires the tournament horizon set to exactly match the preregistered horizons, flattens the challenger's timestamped forward evidence, and fails closed if any observation is malformed, at or before the forward cutoff, outside the registered horizons, or absent.

Only after those checks pass does it call the existing paired proper-score/session-block-bootstrap tournament. The output carries the candidate ID and immutable-material SHA-256 alongside the eligibility audit, making the research conclusion traceable to the preregistered candidate lineage. The adapter does not alter incumbent or challenger probabilities and does not promote a candidate automatically.

## Stage 4 — bounded hypothesis-to-candidate builder

`backend/evals/adaptive_hypothesis_candidate.py` converts exactly one already-qualified diagnostic failure pattern into a research-only candidate spec and immediately passes it through the immutable registry. The builder accepts only the diagnostic dimensions produced by Stage 1, carries the selected horizon and observed failure statistics into the frozen evaluation protocol, and uses the diagnostics creation time as the development-evidence cutoff.

The caller must supply the exact candidate code SHA, an explicit change summary, the downstream evaluation contract and a strictly later forward cutoff. Empty or unqualified diagnostics, unsupported/tampered dimensions, same-time cutoffs, and diagnostics that do not preserve the same-evidence-promotion guard fail closed. The builder never writes model weights, changes runtime probabilities or promotes a challenger.

## Anti-leakage boundary

Any challenger whose design is influenced by diagnostic evidence must receive a new immutable candidate identity and a later preregistered forward cohort. The observations used to discover a weakness cannot approve the challenger created from that weakness. Paired incumbent/challenger scoring, proper scores, calibration diagnostics and session-block bootstrap remain separate downstream gates.

## Non-goals

The adaptive research loop does not retrain V3.1 or V5 in place, change runtime thresholds, alter risk policy, submit orders or promote a model automatically. It does not inspect or modify broker state.

## Next stage

Use the bounded builder only when settled diagnostics contain a sufficiently covered failure pattern and a concrete research change exists. Then collect a genuinely new post-cutoff cohort and run the registered tournament. If the cohort is too small or the challenger does not improve proper-score/calibration evidence without material regressions, retain the incumbent and record the rejection rather than modifying production.
