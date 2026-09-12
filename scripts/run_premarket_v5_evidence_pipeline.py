from __future__ import annotations

import argparse
from datetime import date
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

from premarket_directional_v4_common import PREMARKET_TARGETS


PIPELINE_VERSION = "premarket-v5-evidence-pipeline-v5"
DEFAULT_TARGETS = tuple(PREMARKET_TARGETS)
REPRODUCIBILITY_FILES = [
    "scripts/collect_alpaca_extended_history.py",
    "scripts/build_premarket_training_dataset_v2.py",
    "scripts/audit_premarket_dataset_readiness.py",
    "scripts/audit_premarket_dataset_provenance.py",
    "scripts/run_premarket_v5_decision_preflight.py",
    "scripts/run_premarket_v5_validation.py",
    "scripts/evaluate_premarket_v5_research_gate.py",
    "scripts/validate_premarket_directional_v5_event_nested.py",
    "scripts/validate_premarket_directional_v5_walkforward.py",
    "scripts/premarket_directional_v4_common.py",
    "scripts/premarket_directional_v5_common.py",
    "scripts/train_premarket_predictive.py",
    "backend/app/services/premarket_predictive_engine.py",
    "backend/requirements.txt",
]
REPRODUCIBILITY_PACKAGES = ["numpy", "pandas", "pytest", "httpx", "python-dotenv"]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_symbols(values: list[str]) -> list[str]:
    symbols: list[str] = []
    for value in values:
        for item in str(value).split(","):
            symbol = item.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    if not symbols:
        raise ValueError("At least one ticker is required")
    return symbols


def build_commands(
    *,
    symbols: list[str],
    start: str,
    end: str,
    feed: str,
    raw: Path,
    dataset: Path,
    readiness: Path,
    preflight: Path,
    validation: Path,
    skip_collect: bool,
    targets: list[str],
) -> list[list[str]]:
    scripts = Path(__file__).resolve().parent
    commands: list[list[str]] = []
    if not skip_collect:
        commands.append([
            sys.executable,
            str(scripts / "collect_alpaca_extended_history.py"),
            "--symbols",
            *symbols,
            "--start",
            start,
            "--end",
            end,
            "--feed",
            feed,
            "--output",
            str(raw),
        ])
    commands.extend([
        [
            sys.executable,
            str(scripts / "build_premarket_training_dataset_v2.py"),
            str(raw),
            "--output",
            str(dataset),
        ],
        [
            sys.executable,
            str(scripts / "audit_premarket_dataset_readiness.py"),
            str(dataset),
            "--output",
            str(readiness),
        ],
        [
            sys.executable,
            str(scripts / "run_premarket_v5_decision_preflight.py"),
            str(dataset),
            "--output",
            str(preflight),
        ],
        [
            sys.executable,
            str(scripts / "run_premarket_v5_validation.py"),
            str(dataset),
            "--preflight",
            str(preflight),
            "--output",
            str(validation),
            "--targets",
            *targets,
        ],
        [
            sys.executable,
            str(scripts / "evaluate_premarket_v5_research_gate.py"),
            str(validation),
            "--manifest",
            str(validation.with_suffix(validation.suffix + ".manifest.json")),
            "--output",
            str(validation.with_suffix(validation.suffix + ".gate.json")),
        ],
    ])
    return commands


def artifact_identity(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "sha256": None}
    return {"path": str(path), "exists": True, "sha256": file_sha256(path)}


def package_versions(package_names: list[str] | None = None) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package_name in package_names or REPRODUCIBILITY_PACKAGES:
        try:
            versions[package_name] = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            versions[package_name] = None
    return versions


def git_head(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def execution_identity(repo_root: Path | None = None) -> dict:
    root = repo_root or Path(__file__).resolve().parents[1]
    return {
        "git_head": git_head(root),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "platform": platform.platform(),
        "packages": package_versions(),
        "code_artifacts": {
            relative_path: artifact_identity(root / relative_path)
            for relative_path in REPRODUCIBILITY_FILES
        },
    }


def write_pipeline_manifest(
    output: Path,
    *,
    symbols: list[str],
    start: str,
    end: str,
    feed: str,
    raw: Path,
    dataset: Path,
    readiness: Path,
    preflight: Path,
    validation: Path,
    targets: list[str],
    status: str,
    repo_root: Path | None = None,
) -> Path:
    artifacts = {
        "raw_csv": artifact_identity(raw),
        "raw_manifest": artifact_identity(raw.with_suffix(raw.suffix + ".manifest.json")),
        "dataset_csv": artifact_identity(dataset),
        "dataset_manifest": artifact_identity(dataset.with_suffix(dataset.suffix + ".manifest.json")),
        "readiness_report": artifact_identity(readiness),
        "decision_preflight": artifact_identity(preflight),
        "validation_report": artifact_identity(validation),
        "validation_manifest": artifact_identity(validation.with_suffix(validation.suffix + ".manifest.json")),
        "research_gate": artifact_identity(validation.with_suffix(validation.suffix + ".gate.json")),
    }
    payload = {
        "pipeline_version": PIPELINE_VERSION,
        "status": status,
        "target_contract": "shared_PREMARKET_TARGETS_exact",
        "request": {
            "symbols": symbols,
            "start": start,
            "end": end,
            "feed": feed,
            "targets": targets,
        },
        "execution": execution_identity(repo_root),
        "artifacts": artifacts,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def validate_request(start: str, end: str, feed: str, targets: list[str]) -> None:
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)
    if end_day < start_day:
        raise ValueError("--end must be on or after --start")
    if feed not in {"iex", "sip"}:
        raise ValueError("--feed must be iex or sip")
    expected = list(DEFAULT_TARGETS)
    if list(targets) != expected:
        raise ValueError(
            "Audited evidence runs must include the exact shared PREMARKET_TARGETS set in contract order: "
            f"expected={expected} got={list(targets)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Orion's reproducible Premarket v5 evidence chain: collect -> build -> readiness -> "
            "content-addressed decision preflight -> bound event-nested validation -> validation manifest -> "
            "content-addressed research gate."
        )
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--raw", type=Path, default=Path("backend/data/raw/alpaca_extended_minutes.csv"))
    parser.add_argument("--dataset", type=Path, default=Path("backend/data/premarket_training_dataset_v2.csv"))
    parser.add_argument("--readiness", type=Path, default=Path("backend/data/models/premarket_dataset_readiness.json"))
    parser.add_argument("--preflight", type=Path, default=Path("backend/data/models/premarket_v5_decision_preflight.json"))
    parser.add_argument("--validation", type=Path, default=Path("backend/data/models/premarket_directional_v5_event_nested.json"))
    parser.add_argument("--manifest", type=Path, default=Path("backend/data/models/premarket_v5_evidence_pipeline.json"))
    parser.add_argument("--skip-collect", action="store_true", help="Reuse an existing raw CSV plus its provenance manifest")
    parser.add_argument("--plan", action="store_true", help="Print the deterministic command plan without executing it")
    parser.add_argument("--targets", nargs="+", choices=DEFAULT_TARGETS, default=list(DEFAULT_TARGETS))
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    targets = list(args.targets)
    validate_request(args.start, args.end, args.feed, targets)
    commands = build_commands(
        symbols=symbols,
        start=args.start,
        end=args.end,
        feed=args.feed,
        raw=args.raw,
        dataset=args.dataset,
        readiness=args.readiness,
        preflight=args.preflight,
        validation=args.validation,
        skip_collect=args.skip_collect,
        targets=targets,
    )

    if args.plan:
        print(json.dumps({"pipeline_version": PIPELINE_VERSION, "commands": commands}, indent=2))
        return

    status = "FAILED"
    try:
        for command in commands:
            print("RUN:", " ".join(command), flush=True)
            subprocess.run(command, check=True)
        status = "COMPLETED"
    finally:
        manifest_path = write_pipeline_manifest(
            args.manifest,
            symbols=symbols,
            start=args.start,
            end=args.end,
            feed=args.feed,
            raw=args.raw,
            dataset=args.dataset,
            readiness=args.readiness,
            preflight=args.preflight,
            validation=args.validation,
            targets=targets,
            status=status,
        )
        print(f"Evidence pipeline manifest: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
