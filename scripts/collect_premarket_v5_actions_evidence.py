from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any


API_VERSION = "2022-11-28"
WORKFLOW_FILE = "premarket-v5-cloud-shadow.yml"
ARTIFACT_PREFIX = "premarket-v5-shadow-"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
REQUIRED_ARTIFACT_RETENTION_DAYS = 90
RETENTION_TOLERANCE_SECONDS = 5 * 60
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ActionsEvidenceError(RuntimeError):
    pass


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        source_host = urllib.parse.urlsplit(req.full_url).netloc.lower()
        target_host = urllib.parse.urlsplit(redirected.full_url).netloc.lower()
        if source_host != target_host:
            redirected.remove_header("Authorization")
        return redirected


def _iso_utc(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ActionsEvidenceError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ActionsEvidenceError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _git_sha(value: Any, *, field: str) -> str:
    sha = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(sha):
        raise ActionsEvidenceError(f"{field} must be a 40-character hexadecimal commit SHA")
    return sha


def normalize_run(run: dict[str, Any]) -> dict[str, Any]:
    required = ("id", "event", "display_title", "created_at", "status", "run_attempt", "head_sha")
    missing = [field for field in required if field not in run]
    if missing:
        raise ActionsEvidenceError(f"workflow run missing fields: {', '.join(missing)}")
    _iso_utc(run["created_at"], field="created_at")
    return {
        "id": str(run["id"]),
        "event": str(run["event"]),
        "display_title": str(run["display_title"]),
        "created_at": str(run["created_at"]),
        "status": str(run["status"]),
        "conclusion": run.get("conclusion"),
        "run_attempt": int(run["run_attempt"]),
        "head_sha": _git_sha(run["head_sha"], field="head_sha"),
    }


def select_shadow_artifact(artifacts: list[dict[str, Any]], *, run_id: str) -> dict[str, Any] | None:
    expected_suffix = f"-{run_id}"
    candidates = [
        artifact
        for artifact in artifacts
        if str(artifact.get("name", "")).startswith(ARTIFACT_PREFIX)
        and str(artifact.get("name", "")).endswith(expected_suffix)
        and not bool(artifact.get("expired"))
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        names = sorted(str(row.get("name")) for row in candidates)
        raise ActionsEvidenceError(f"run {run_id} has ambiguous Premarket V5 artifacts: {names}")
    return candidates[0]


def artifact_retention_contract(artifact: dict[str, Any], *, run_id: str) -> tuple[str, float]:
    created_at = _iso_utc(artifact.get("created_at"), field=f"run {run_id} artifact created_at")
    expires_at = _iso_utc(artifact.get("expires_at"), field=f"run {run_id} artifact expires_at")
    retention_seconds = (expires_at - created_at).total_seconds()
    minimum_seconds = REQUIRED_ARTIFACT_RETENTION_DAYS * 24 * 60 * 60
    if retention_seconds <= 0:
        raise ActionsEvidenceError(f"run {run_id} artifact expires_at must be after created_at")
    if retention_seconds + RETENTION_TOLERANCE_SECONDS < minimum_seconds:
        observed_days = retention_seconds / (24 * 60 * 60)
        raise ActionsEvidenceError(
            f"run {run_id} artifact retention is {observed_days:.3f} days; "
            f"Issue #3 requires at least {REQUIRED_ARTIFACT_RETENTION_DAYS} days"
        )
    return expires_at.isoformat().replace("+00:00", "Z"), retention_seconds / (24 * 60 * 60)


def prediction_payload_from_zip(
    blob: bytes,
    *,
    run_id: str,
    run_attempt: int,
    head_sha: str,
) -> dict[str, Any]:
    if len(blob) > MAX_ARTIFACT_BYTES:
        raise ActionsEvidenceError(f"run {run_id} artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise ActionsEvidenceError(f"run {run_id} artifact is not a valid zip") from exc

    candidates: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ActionsEvidenceError(f"run {run_id} artifact contains unsafe path: {info.filename}")
        name = path.name
        if name.startswith("prediction-") and name.endswith(".json") and not name.endswith(".manifest.json"):
            candidates.append(info)
    if len(candidates) != 1:
        raise ActionsEvidenceError(f"run {run_id} artifact must contain exactly one prediction JSON")
    info = candidates[0]
    if info.file_size > MAX_ARTIFACT_BYTES:
        raise ActionsEvidenceError(f"run {run_id} prediction JSON is too large")
    try:
        payload = json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActionsEvidenceError(f"run {run_id} prediction JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ActionsEvidenceError(f"run {run_id} prediction payload must be an object")
    provenance = payload.get("acquisition_provenance")
    if not isinstance(provenance, dict) or str(provenance.get("github_run_id")) != str(run_id):
        raise ActionsEvidenceError(f"run {run_id} prediction payload is not bound to the workflow run")
    try:
        payload_attempt = int(provenance.get("github_run_attempt"))
    except (TypeError, ValueError) as exc:
        raise ActionsEvidenceError(f"run {run_id} prediction payload has invalid github_run_attempt") from exc
    if payload_attempt != int(run_attempt):
        raise ActionsEvidenceError(
            f"run {run_id} prediction payload attempt {payload_attempt} does not match workflow attempt {run_attempt}"
        )
    expected_sha = _git_sha(head_sha, field=f"run {run_id} head_sha")
    payload_sha = _git_sha(provenance.get("github_head_sha"), field=f"run {run_id} prediction github_head_sha")
    if payload_sha != expected_sha:
        raise ActionsEvidenceError(
            f"run {run_id} prediction payload commit {payload_sha} does not match workflow head_sha {expected_sha}"
        )
    return payload


class GitHubActionsClient:
    def __init__(self, *, repository: str, token: str, api_url: str = "https://api.github.com") -> None:
        if repository.count("/") != 1:
            raise ActionsEvidenceError("repository must be owner/name")
        if not token:
            raise ActionsEvidenceError("GitHub token is required")
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")
        self._opener = urllib.request.build_opener(_SafeRedirectHandler())

    def _request(self, path: str, *, accept: str = "application/vnd.github+json") -> bytes:
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            headers={
                "Accept": accept,
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "orion-premarket-v5-evidence-health",
            },
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ActionsEvidenceError(f"GitHub API {exc.code} for {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ActionsEvidenceError(f"GitHub API request failed for {path}: {exc}") from exc

    def _json(self, path: str) -> dict[str, Any]:
        try:
            payload = json.loads(self._request(path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActionsEvidenceError(f"GitHub API returned invalid JSON for {path}") from exc
        if not isinstance(payload, dict):
            raise ActionsEvidenceError(f"GitHub API returned non-object JSON for {path}")
        return payload

    def scheduled_runs(self, *, start_date: date) -> list[dict[str, Any]]:
        workflow = urllib.parse.quote(WORKFLOW_FILE, safe="")
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        result: list[dict[str, Any]] = []
        for page in range(1, 11):
            path = (
                f"/repos/{self.repository}/actions/workflows/{workflow}/runs"
                f"?event=schedule&per_page=100&page={page}"
            )
            rows = self._json(path).get("workflow_runs", [])
            if not isinstance(rows, list):
                raise ActionsEvidenceError("workflow_runs must be an array")
            if not rows:
                break
            stop = False
            for raw in rows:
                if not isinstance(raw, dict):
                    raise ActionsEvidenceError("workflow run entry must be an object")
                created = _iso_utc(raw.get("created_at"), field="created_at")
                if created < start:
                    stop = True
                    continue
                result.append(normalize_run(raw))
            if stop or len(rows) < 100:
                break
        return sorted(result, key=lambda row: (row["created_at"], int(row["id"]), row["run_attempt"]))

    def run_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        payload = self._json(f"/repos/{self.repository}/actions/runs/{run_id}/artifacts?per_page=100")
        rows = payload.get("artifacts", [])
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ActionsEvidenceError(f"run {run_id} artifacts response is invalid")
        return rows

    def download_artifact(self, artifact_id: int) -> bytes:
        # GitHub's artifact download endpoint is an API endpoint that returns a
        # temporary redirect to the ZIP. The API request must use GitHub's JSON
        # media type; the redirect target still returns the binary archive.
        return self._request(f"/repos/{self.repository}/actions/artifacts/{artifact_id}/zip")


def collect(client: GitHubActionsClient, *, start_date: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    runs = client.scheduled_runs(start_date=start_date)
    payloads: list[dict[str, Any]] = []
    missing_artifact_run_ids: list[str] = []
    live_artifact_expiries: list[str] = []
    live_artifact_retention_days: list[float] = []
    for run in runs:
        if run["status"] != "completed" or run.get("conclusion") != "success":
            continue
        run_id = str(run["id"])
        run_attempt = int(run["run_attempt"])
        artifact = select_shadow_artifact(client.run_artifacts(run_id), run_id=run_id)
        if artifact is None:
            missing_artifact_run_ids.append(run_id)
            continue
        expires_at, retention_days = artifact_retention_contract(artifact, run_id=run_id)
        live_artifact_expiries.append(expires_at)
        live_artifact_retention_days.append(retention_days)
        payloads.append(
            prediction_payload_from_zip(
                client.download_artifact(int(artifact["id"])),
                run_id=run_id,
                run_attempt=run_attempt,
                head_sha=str(run["head_sha"]),
            )
        )
    summary = {
        "score_blind": True,
        "workflow_file": WORKFLOW_FILE,
        "start_date": start_date.isoformat(),
        "scheduled_run_count": len(runs),
        "prediction_artifact_count": len(payloads),
        "successful_runs_missing_live_artifact_count": len(missing_artifact_run_ids),
        "successful_runs_missing_live_artifact_ids": missing_artifact_run_ids,
        "required_artifact_retention_days": REQUIRED_ARTIFACT_RETENTION_DAYS,
        "minimum_observed_artifact_retention_days": (
            min(live_artifact_retention_days) if live_artifact_retention_days else None
        ),
        "earliest_live_artifact_expires_at": min(live_artifact_expiries) if live_artifact_expiries else None,
    }
    return runs, payloads, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect score-blind Premarket V5 GitHub Actions run metadata and live artifacts.")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        client = GitHubActionsClient(repository=args.repository, token=args.token, api_url=args.api_url)
        runs, payloads, summary = collect(client, start_date=args.start_date)
    except (ActionsEvidenceError, OSError, ValueError) as exc:
        print(json.dumps({"status": "actions_evidence_collection_failed", "error": str(exc)}, sort_keys=True))
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "runs.json").write_text(json.dumps({"workflow_runs": runs}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload_dir = args.output_dir / "predictions"
    payload_dir.mkdir(exist_ok=True)
    for payload in payloads:
        provenance = payload["acquisition_provenance"]
        run_id = str(provenance["github_run_id"])
        (payload_dir / f"prediction-{run_id}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "collection-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
