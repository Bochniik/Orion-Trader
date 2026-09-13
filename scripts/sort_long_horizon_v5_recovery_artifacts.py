from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _parse_created_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid artifact created_at timestamp: {value}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"Artifact created_at timestamp must be timezone-aware: {value}")
    return parsed.astimezone(timezone.utc)


def sort_artifact_rows(lines: Iterable[str]) -> list[str]:
    rows: list[tuple[datetime, int, str]] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise ValueError(f"Expected artifact TSV row with 3 fields, got {len(parts)}")
        artifact_id_raw, artifact_name, created_at_raw = parts
        try:
            artifact_id = int(artifact_id_raw)
        except ValueError:
            raise ValueError(f"Invalid artifact id: {artifact_id_raw}") from None
        if artifact_id <= 0:
            raise ValueError(f"Artifact id must be positive: {artifact_id_raw}")
        if not artifact_name:
            raise ValueError("Artifact name must not be empty")
        created_at = _parse_created_at(created_at_raw)
        rows.append((created_at, artifact_id, line))

    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [line for _, _, line in rows]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically sort GitHub Actions artifact metadata newest-first before "
            "long-horizon V5 recovery."
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
