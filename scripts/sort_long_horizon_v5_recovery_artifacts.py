from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Iterable


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_MIN_RETENTION_BY_PREFIX = {
    "long-horizon-v5-paired-shadow-": timedelta(days=45),
    "long-horizon-v5-evidence-ledger-": timedelta(days=90),
}
_RECOVERY_IDENTITY_PREFIXES = tuple(_MIN_RETENTION_BY_PREFIX)


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid artifact {field_name} timestamp: {value}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"Artifact {field_name} timestamp must be timezone-aware: {value}")
    return parsed.astimezone(timezone.utc)


def _minimum_retention(artifact_name: str) -> timedelta | None:
    for prefix, minimum in _MIN_RETENTION_BY_PREFIX.items():
        if artifact_name.startswith(prefix):
            return minimum
    return None


def _recovery_identity(artifact_name: str, workflow_run_id: int) -> tuple[str, int] | None:
    for prefix in _RECOVERY_IDENTITY_PREFIXES:
        if artifact_name.startswith(prefix):
            return prefix, workflow_run_id
    return None


def sort_artifact_rows(lines: Iterable[str]) -> list[str]:
    rows: list[tuple[datetime, int, str]] = []
    seen_recovery_identities: dict[tuple[str, int], tuple[int, str]] = {}
    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 6:
            raise ValueError(f"Expected artifact TSV row with 6 fields, got {len(parts)}")
        (
            artifact_id_raw,
            artifact_name,
            created_at_raw,
            expires_at_raw,
            workflow_run_id_raw,
            workflow_head_sha,
        ) = parts
        if not artifact_name:
            raise ValueError("Artifact name must not be empty")

        minimum_retention = _minimum_retention(artifact_name)
        if minimum_retention is None:
            continue

        try:
            artifact_id = int(artifact_id_raw)
        except ValueError:
            raise ValueError(f"Invalid artifact id: {artifact_id_raw}") from None
        if artifact_id <= 0:
            raise ValueError(f"Artifact id must be positive: {artifact_id_raw}")
        try:
            workflow_run_id = int(workflow_run_id_raw)
        except ValueError:
            raise ValueError(f"Invalid artifact workflow_run.id: {workflow_run_id_raw}") from None
        if workflow_run_id <= 0:
            raise ValueError(f"Artifact workflow_run.id must be positive: {workflow_run_id_raw}")
        if not _GIT_SHA_RE.fullmatch(workflow_head_sha):
            raise ValueError("Artifact workflow_run.head_sha must be a 40-character hexadecimal commit SHA")

        created_at = _parse_timestamp(created_at_raw, "created_at")
        expires_at = _parse_timestamp(expires_at_raw, "expires_at")
        if expires_at <= created_at:
            raise ValueError(f"Artifact expires_at must be after created_at: {artifact_name}")

        if expires_at - created_at < minimum_retention:
            actual_days = (expires_at - created_at).total_seconds() / 86400.0
            required_days = int(minimum_retention.total_seconds() // 86400)
            raise ValueError(
                f"Artifact retention shorter than required: {artifact_name} "
                f"actual_days={actual_days:.3f} required_days={required_days}"
            )

        recovery_identity = _recovery_identity(artifact_name, workflow_run_id)
        if recovery_identity is not None:
            previous = seen_recovery_identities.get(recovery_identity)
            if previous is not None:
                previous_artifact_id, previous_name = previous
                raise ValueError(
                    "Ambiguous duplicate recovery artifact for producing run: "
                    f"run_id={workflow_run_id} artifact_type={recovery_identity[0]} "
                    f"artifact_ids={previous_artifact_id},{artifact_id} "
                    f"artifact_names={previous_name},{artifact_name}"
                )
            seen_recovery_identities[recovery_identity] = (artifact_id, artifact_name)

        rows.append((created_at, artifact_id, line))

    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [line for _, _, line in rows]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ignore unrelated repository artifacts, validate retention/provenance metadata for long-horizon "
            "recovery artifacts, reject ambiguous duplicates, and sort eligible artifacts newest-first."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    sorted_rows = sort_artifact_rows(args.input.read_text(encoding="utf-8").splitlines())
    args.output.write_text("\n".join(sorted_rows) + ("\n" if sorted_rows else ""), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
