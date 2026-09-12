# Research Lineage & Holdout Contamination Guard

Status: research integrity infrastructure only. No runtime model, threshold, calibration, risk policy, broker path or order behavior is changed.

## Why this exists

The sector-specialist historical screen and leave-one-out audit inspected the same 60d/5m market window. Those results can inspire a new hypothesis, but that inspected cohort can no longer serve as untouched decisive evidence for a child candidate.

The registry makes that constraint machine-readable. Every research dataset receives a stable logical identity and a role (`screening`, `diagnostic`, or `decisive`). Every candidate records which datasets inspired it and which datasets are intended as decisive evidence.

## Fail-closed rules

- A dataset identity already used to inspire a candidate cannot later be relabelled as decisive evidence for that candidate.
- Only datasets explicitly registered with role `decisive` may be used as decisive evidence.
- One decisive dataset identity cannot be reused across multiple candidate identities.
- Unknown dataset references, duplicate IDs, malformed roles, or missing hypothesis freeze timestamps fail validation.

These checks do not prove that a dataset is causally clean by themselves; they prevent a known class of accidental holdout reuse once a cohort has been inspected.

## Current specialist lineage

The yfinance 60d/5m cohort ending 2026-09-11, covering SPY plus AAPL/MSFT/NVDA/AMD/AMZN/TSLA/META/GOOGL, is registered as diagnostic/inspected because it was used by the sector screen and leave-one-out robustness audit. Any future industry-specialist hypothesis inspired by those results must use a different decisive dataset identity.

## Next logical step

Before implementing a semiconductor or other industry specialist, freeze its cohort, horizons, feature family and evaluation gate in the registry/protocol. Historical data may still be used for falsification, but decisive promotion-quality evidence must be assigned a fresh identity collected after the hypothesis is frozen.
