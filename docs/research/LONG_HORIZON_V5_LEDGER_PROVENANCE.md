# Long-horizon V5 cumulative-ledger provenance

Date fixed: 2026-09-13

This hardening step closes the provenance gap between authenticated long-horizon V5 prediction artifacts and the cumulative append-only evidence ledger. It is research infrastructure only: it does not modify model probabilities, calibration, thresholds, risk policy, runtime recommendations, broker behavior, or order submission.

## Problem

The long-horizon evidence cycle already integrity-sealed cumulative ledger records and authenticated recovered prediction artifacts against their exact GitHub Actions workflow run. However, recovery of the *prior cumulative ledger* still selected a `long-horizon-v5-evidence-ledger-*` artifact by name and then trusted the ledger payload's internal record digest. That protected against record corruption or truncation, but it did not prove that the ledger artifact itself came from the expected scheduled evidence-cycle run.

A second operational risk exists at the artifact-storage layer: workflow YAML can request a retention period, while repository/org policy may shorten the actual GitHub Actions artifact lifetime. Because the forward protocol depends on historical prediction artifacts and a cumulative ledger, silently shortened retention can turn a healthy collection process into an unrecoverable evidence gap. The recovery path therefore treats GitHub's actual `created_at`/`expires_at` metadata as part of the evidence contract instead of trusting YAML intent alone.

## Provenance contract

Every newly uploaded cumulative ledger is now attested with `orion-long-horizon-v5-evidence-cycle-provenance-v1`. The attestation binds the ledger to:

- the exact evidence-cycle workflow path;
- GitHub Actions run ID;
- run attempt;
- workflow head commit SHA;
- triggering event (`schedule` or `workflow_dispatch`);
- a deterministic SHA-256 over the ledger payload excluding the provenance object itself.

Only scheduled runs are marked `forward_eligible=true`.

On recovery, the workflow parses the run ID from the artifact name, fetches GitHub's run metadata, requires the expected evidence-cycle workflow path, a successful completed scheduled run, an exact run-attempt match, an exact head-SHA match, and an exact ledger-content SHA-256 match. Manual workflow-dispatch ledger artifacts are skipped as forward lineage candidates rather than allowed to shadow the latest scheduled ledger.

The repository-wide artifact listing is also treated as provenance evidence rather than only as a name index. Before any candidate prediction or ledger artifact is downloaded, its GitHub artifact metadata must expose a positive `workflow_run.id` and a 40-character `workflow_run.head_sha`. The producing run ID must match the run encoded in the artifact name, and the artifact's producing head SHA must match the head SHA returned by GitHub for that exact run. Missing or conflicting artifact-level run metadata fails closed. This prevents a same-repository artifact from another workflow run from being accepted merely because its name and embedded payload imitate an expected run.

## Retention contract

Recovery validates the actual GitHub artifact lifetime from timezone-aware `created_at` and `expires_at` metadata before any prediction or ledger candidate can be used.

- `long-horizon-v5-paired-shadow-*` artifacts must retain at least 45 days, matching the immutable paired-shadow upload contract and comfortably exceeding the 35-day recovery window.
- `long-horizon-v5-evidence-ledger-*` artifacts must retain at least 90 days, matching the cumulative-ledger upload contract.
- Missing, malformed or non-increasing timestamps fail closed.
- A repository/org retention cap that shortens either required lifetime therefore surfaces immediately as an operational failure instead of silently deleting forward evidence later.

This check remains score-blind: it inspects storage metadata only and cannot expose model probabilities, labels or proper-score metrics.

## Controlled migration

A one-way migration is permitted for the immediately preceding legacy ledger format because older artifacts predate the new outer provenance object. Migration is allowed only when all of the following hold:

1. the artifact name resolves to the exact successful scheduled evidence-cycle run;
2. GitHub reports the expected workflow path;
3. the legacy ledger carries the existing SHA-256 integrity seal with record count and records digest;
4. that integrity seal validates before the ledger is accepted.

An unsealed legacy ledger is not eligible for migration. The next successful cycle rewrites the cumulative ledger with the new provenance contract, after which normal strict validation applies.

## Score blindness

The provenance validator does not inspect probabilities, directions, realized labels, Brier score, log loss, directional accuracy, ECE, or tournament deltas. It validates only origin, immutable ledger integrity, artifact lifetime, and workflow identity. Therefore this hardening does not create a path for outcome-driven early stopping or tuning before the pre-registered maturity gates.

## Failure semantics

Recovery fails closed on malformed artifact IDs, malformed artifact producing-run metadata, malformed retention timestamps, shortened required retention, artifact/run-ID mismatch, artifact/run head-SHA mismatch, unexpected workflow paths, unsuccessful scheduled runs, run-attempt drift, commit-SHA drift, unsupported provenance contracts, internal ledger-integrity failures, or content-digest drift. A manual-run ledger is ignored for forward lineage. This keeps the forward evidence chain anchored to genuine scheduled collection while preserving manual diagnostics.

## Next logical step

Observe the first scheduled evidence-cycle recovery after this change. Confirm that recovered prediction and ledger candidates carry artifact-level producing-run metadata that agrees with the separately fetched run metadata and that GitHub reports at least the required 45/90-day actual retention. Then confirm the one-way legacy migration/strict provenance transition. After that, further work should target measured collection-health blockers rather than adding provenance layers unless a concrete new integrity gap is found.