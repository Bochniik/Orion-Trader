# Challenger preregistration tournament gate — 2026-09-19

Branch: `research/require-challenger-registration`

## Purpose

Close the leakage-control gap between the immutable adaptive challenger registry and the paired regular-hours challenger tournament. A challenger can no longer receive a research-eligible tournament conclusion unless its identity and forward boundary were frozen before the evaluated evidence.

## Policy

- `compare_reports` requires a validated immutable registry payload.
- The CLI requires `--registration`.
- Every tournament horizon must be covered by the frozen registration.
- Every challenger observation is checked before scoring and must be strictly later than the registered forward cutoff.
- Pre-cutoff evidence fails closed; it is never silently filtered.
- Output records candidate ID, immutable-material SHA-256, cutoff and checked observation count.
- Tournament contract is `orion-intraday-challenger-tournament-v2` and declares preregistration mandatory.
- This remains offline research infrastructure. No incumbent weights, calibration, thresholds, risk policy, runtime prediction path, broker behavior, order path or promotion state is modified.

## Regression coverage

Tests retain exact pairing, duplicate/outcome integrity, proper-score and session-block-bootstrap behavior, insufficient-session rejection and all-horizon gating. New cases verify valid post-cutoff registration, fail-closed rejection of pre-cutoff evidence, and rejection when the frozen registration omits a required horizon.

## Next logical step

After CI is green, add a bounded hypothesis-to-candidate builder. It may translate settled failure patterns into explicit research candidate specifications, but each candidate must be registered before forward collection, the search space must remain small and auditable, and the builder must have no path to automatic incumbent modification or promotion.
