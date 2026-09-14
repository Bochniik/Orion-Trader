from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
WORKFLOW_PATH = ".github/workflows/premarket-v5-cloud-shadow.yml"


class GuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryDecision:
    collect_allowed: bool
    reason: str
    blocking_run_id: int | None = None
    blocking_artifact: str | None = None


def _local_session(created_at: str) -> date:
    value = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise GuardError("GitHub run created_at must be timezone-aware")
    return value.astimezone(NY).date()


def decide_recovery(
    *,
    runs: list[dict[str, Any]],
    artifacts_by_run: dict[int, list[dict[str, Any]]],
    session: date,
    snapshot: str,
    current_run_id: int,
) -> RecoveryDecision:
    prefix = f"premarket-v5-shadow-{snapshot}-"
    eligible_runs: list[dict[str, Any]] = []
    for run in runs:
        try:
            run_id = int(run["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GuardError("GitHub run payload is missing a valid id") from exc
        if run_id == current_run_id:
            continue
        if run.get("event") != "schedule":
            continue
        if run.get("path") != WORKFLOW_PATH:
            continue
        if run.get("head_branch") != "main":
            continue
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        created_at = run.get("created_at")
        if not isinstance(created_at, str):
            raise GuardError(f"GitHub run {run_id} is missing created_at")
        if _local_session(created_at) != session:
            continue
        eligible_runs.append(run)

    for run in sorted(eligible_runs, key=lambda item: int(item["id"]), reverse=True):
        run_id = int(run["id"])
        for artifact in artifacts_by_run.get(run_id, []):
            name = artifact.get("name")
            if not isinstance(name, str):
                continue
            if artifact.get("expired") is True:
                continue
            if name.startswith(prefix):
                return RecoveryDecision(
                    collect_allowed=False,
                    reason="existing_successful_evidence",
                    blocking_run_id=run_id,
                    blocking_artifact=name,
                )

    return RecoveryDecision(collect_allowed=True, reason="no_successful_evidence")


def _api_json(url: str, token: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "orion-premarket-v5-recovery-guard",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed GitHub API origin
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GuardError(f"GitHub API request failed for {url}: {exc}") from exc


def fetch_decision(
    *,
    repository: str,
    token: str,
    session: date,
    snapshot: str,
    current_run_id: int,
) -> RecoveryDecision:
    api_root = f"https://api.github.com/repos/{repository}"
    runs_payload = _api_json(f"{api_root}/actions/runs?event=schedule&per_page=100", token)
    runs = runs_payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise GuardError("GitHub runs response is missing workflow_runs")

    artifacts_by_run: dict[int, list[dict[str, Any]]] = {}
    candidate_ids: list[int] = []
    for run in runs:
        try:
            run_id = int(run["id"])
            created_at = run.get("created_at")
        except (KeyError, TypeError, ValueError) as exc:
            raise GuardError("GitHub run payload is missing a valid id") from exc
        if run_id == current_run_id:
            continue
        if run.get("event") != "schedule" or run.get("path") != WORKFLOW_PATH:
            continue
        if run.get("head_branch") != "main":
            continue
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        if not isinstance(created_at, str) or _local_session(created_at) != session:
            continue
        candidate_ids.append(run_id)

    for run_id in candidate_ids:
        payload = _api_json(f"{api_root}/actions/runs/{run_id}/artifacts?per_page=100", token)
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise GuardError(f"GitHub artifacts response for run {run_id} is missing artifacts")
        artifacts_by_run[run_id] = artifacts

    return decide_recovery(
        runs=runs,
        artifacts_by_run=artifacts_by_run,
        session=session,
        snapshot=snapshot,
        current_run_id=current_run_id,
    )


def _write_github_output(path: Path, decision: RecoveryDecision) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"collect_allowed={'true' if decision.collect_allowed else 'false'}\n")
        handle.write(f"reason={decision.reason}\n")
        handle.write(f"blocking_run_id={decision.blocking_run_id or ''}\n")
        handle.write(f"blocking_artifact={decision.blocking_artifact or ''}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed, score-blind idempotency guard for Premarket V5 recovery slots.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--session", required=True, help="NYSE session date YYYY-MM-DD")
    parser.add_argument("--snapshot", choices=("early", "mid", "late"), required=True)
    parser.add_argument("--current-run-id", type=int, required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    token = os.getenv(args.token_env, "")
    if not token:
        raise GuardError(f"Missing GitHub token in {args.token_env}")
    session = date.fromisoformat(args.session)

    decision = fetch_decision(
        repository=args.repository,
        token=token,
        session=session,
        snapshot=args.snapshot,
        current_run_id=args.current_run_id,
    )
    print(json.dumps({
        "collect_allowed": decision.collect_allowed,
        "reason": decision.reason,
        "blocking_run_id": decision.blocking_run_id,
        "blocking_artifact": decision.blocking_artifact,
    }, sort_keys=True))
    if args.github_output is not None:
        _write_github_output(args.github_output, decision)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as exc:
        print(f"Recovery guard failed closed: {exc}", file=sys.stderr)
        raise SystemExit(2)
