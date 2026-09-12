# Research Lineage & Holdout Contamination Guard

Status: research integrity infrastructure only. No runtime model, threshold, calibration, risk policy, broker path or order behavior is changed.

## Why this exists

The sector-specialist historical screen, leave-one-out audit and semiconductor 3h screen all inspect historical market cohorts. Those results may inspire later hypotheses, but once a candidate has been evaluated on a cohort, that same cohort is no longer untouched evidence for that candidate.

The registry makes that constraint machine-readable. Every research dataset receives a stable logical identity and a role (`screening`, `diagnostic`, or `decisive`). Every candidate records which datasets inspired it, which non-decisive datasets it has already been screened on, and which datasets are intended as decisive evidence.

## Candidate dataset roles

- `inspired_by_datasets`: evidence inspected before the candidate was frozen and used to motivate its hypothesis;
- `screening_datasets`: screening/diagnostic evidence inspected after the candidate was frozen and used to falsify or deprioritize that exact design;
- `decisive_datasets`: fresh promotion-quality holdouts that must remain identity-distinct from both categories above.

A screening dataset must be registered as `screening` or `diagnostic` and explicitly marked `inspected=true`. This prevents a dataset from being listed as candidate exposure while still masquerading as untouched evidence.

## Fail-closed rules

- A dataset identity already used to inspire a candidate cannot later be used as decisive evidence for that candidate.
- A dataset identity already used to screen or diagnose a candidate cannot later be used as decisive evidence for that candidate.
- Only datasets explicitly registered with role `decisive` may be used as decisive evidence.
- A decisive dataset cannot simultaneously be registered as a screening dataset.
- Screening references must point to datasets marked `inspected=true`.
- One decisive dataset identity cannot be reused across multiple candidate identities.
- Unknown dataset references, duplicate candidate dataset references, duplicate IDs, malformed roles, or missing hypothesis freeze timestamps fail validation.

These checks do not prove that a dataset is causally clean by themselves; they prevent known classes of accidental holdout reuse once a cohort has been inspected.

## Current specialist lineage

The yfinance 60d/5m broad-sector cohort ending 2026-09-11 is registered as diagnostic/inspected and linked as screening evidence for `sector-specialist-v1`. It also inspired the later industry-specialist work.

The expanded yfinance 60d/5m semiconductor cohort ending 2026-09-11 is registered as screening/inspected and linked directly to `semiconductor-specialist-3h-v1`. PR #67 rejected that candidate after the preregistered screen degraded Brier, log loss, directional accuracy and ECE. That exact cohort can therefore never become a decisive holdout for the same candidate.

## Next logical step

Do not retune the rejected semiconductor specialist on the already inspected cohort. A materially different industry-aware design requires a new candidate identity, an explicit record of which previous datasets inspired it, and later decisive evidence with a fresh identity that passes this guard.
