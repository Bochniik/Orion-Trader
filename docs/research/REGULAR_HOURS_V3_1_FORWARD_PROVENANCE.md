# Regular-hours V3.1 forward provenance

## Decision

Regular-hours V3.1 forward evidence now requires an authenticated acquisition attestation before an artifact can contribute to the pre-registered score-inspection gate.

The change fixes a contamination risk in which a `workflow_dispatch` diagnostic artifact had the same prediction payload shape as a genuine scheduled run and could therefore enter the forward-readiness population.

## Forward-eligible contract

A newly produced artifact is forward eligible only when all of the following are true:

- it was produced by `event_name == schedule`;
- the regular-hours session gate was active;
- the prediction runner completed normally;
- the artifact is bound to a positive GitHub Actions `workflow_run_id` and `run_attempt`;
- the producing 40-character Git commit SHA is recorded;
- collection start/end timestamps are recorded and ordered;
- the pre-attestation payload is content-addressed with SHA-256.

`workflow_dispatch` remains available for diagnostics but is explicitly `forward_eligible=false`. Off-session scheduled runs are also non-forward.

## Readiness semantics

The score-blind forward-completeness report uses only artifacts carrying a valid `regular-hours-v3-1-acquisition-provenance-v1` attestation with `forward_eligible=true`.

- explicit non-forward diagnostics are counted but excluded;
- older unattested artifacts are counted as legacy/unattested but cannot unlock the forward gate;
- malformed attestations fail closed;
- a manual artifact claiming `forward_eligible=true` fails closed.

The existing 30-complete-session score-inspection threshold is unchanged. Predictive probabilities, directions and proper scores are not traversed by the readiness logic.

## Safety

This is an evidence/provenance change only. It does not modify model weights, features, targets, calibration tables, confidence thresholds, symbol universe, market schedule, risk policy, broker integration, paid APIs or order submission behavior.
