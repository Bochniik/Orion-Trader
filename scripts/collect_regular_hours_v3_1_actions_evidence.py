from __future__ import annotations

import io, json, re, urllib.parse, urllib.request, zipfile
from pathlib import PurePosixPath
from typing import Any

WORKFLOW_FILE="regular-hours-v3-1-cloud-shadow.yml"
ARTIFACT_PREFIX="regular-hours-v3-1-shadow-"
MAX_ARTIFACT_BYTES=8*1024*1024
SHA_RE=re.compile(r"^[0-9a-f]{40}$")

class ActionsEvidenceError(RuntimeError): pass

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
        if redirected is not None and urllib.parse.urlsplit(req.full_url).netloc.lower()!=urllib.parse.urlsplit(redirected.full_url).netloc.lower():
            redirected.remove_header("Authorization")
        return redirected

def select_artifact(artifacts:list[dict[str,Any]],*,run_id:str)->dict[str,Any]|None:
    expected=f"{ARTIFACT_PREFIX}{run_id}"
    candidates=[a for a in artifacts if a.get("name")==expected and not bool(a.get("expired"))]
    if len(candidates)>1: raise ActionsEvidenceError(f"run {run_id} has ambiguous artifacts")
    return candidates[0] if candidates else None

def prediction_payload_from_zip(blob:bytes,*,run_id:str,run_attempt:int,head_sha:str)->dict[str,Any]:
    if len(blob)>MAX_ARTIFACT_BYTES: raise ActionsEvidenceError(f"run {run_id} artifact exceeds size limit")
    try: archive=zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc: raise ActionsEvidenceError(f"run {run_id} artifact is not a valid zip") from exc
    candidates=[]
    for info in archive.infolist():
        path=PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts: raise ActionsEvidenceError(f"run {run_id} artifact contains unsafe path")
        if path.name.startswith("prediction-") and path.name.endswith(".json") and not path.name.endswith(".manifest.json"): candidates.append(info)
    if len(candidates)!=1: raise ActionsEvidenceError(f"run {run_id} artifact must contain exactly one prediction JSON")
    info=candidates[0]
    if info.file_size>MAX_ARTIFACT_BYTES: raise ActionsEvidenceError(f"run {run_id} prediction JSON exceeds size limit")
    try: payload=json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ActionsEvidenceError(f"run {run_id} prediction JSON is invalid") from exc
    if not isinstance(payload,dict): raise ActionsEvidenceError(f"run {run_id} prediction payload must be an object")
    p=payload.get("acquisition_provenance")
    if not isinstance(p,dict): raise ActionsEvidenceError(f"run {run_id} lacks acquisition provenance")
    if str(p.get("workflow_run_id"))!=str(run_id): raise ActionsEvidenceError(f"run {run_id} workflow binding mismatch")
    try: attempt=int(p.get("run_attempt"))
    except (TypeError,ValueError) as exc: raise ActionsEvidenceError(f"run {run_id} invalid run_attempt") from exc
    if attempt!=int(run_attempt): raise ActionsEvidenceError(f"run {run_id} attempt mismatch")
    expected_sha=str(head_sha).lower(); observed_sha=str(p.get("github_head_sha","")).lower()
    if not SHA_RE.fullmatch(expected_sha) or observed_sha!=expected_sha: raise ActionsEvidenceError(f"run {run_id} commit mismatch")
    if p.get("event_name")!="schedule" or p.get("forward_eligible") is not True: raise ActionsEvidenceError(f"run {run_id} is not forward-eligible scheduled evidence")
    return payload

class GitHubActionsClient:
    def __init__(self,*,repository:str,token:str,api_url:str="https://api.github.com"):
        if repository.count("/")!=1 or not token: raise ActionsEvidenceError("repository owner/name and token required")
        self.repository=repository; self.token=token; self.api_url=api_url.rstrip("/"); self.opener=urllib.request.build_opener(SafeRedirectHandler())
    def request(self,path:str)->bytes:
        req=urllib.request.Request(f"{self.api_url}{path}",headers={"Accept":"application/vnd.github+json","Authorization":f"Bearer {self.token}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"orion-regular-hours-evidence"})
        with self.opener.open(req,timeout=30) as response: return response.read()
    def json(self,path:str)->dict[str,Any]:
        value=json.loads(self.request(path).decode("utf-8"))
        if not isinstance(value,dict): raise ActionsEvidenceError("GitHub API returned non-object JSON")
        return value
    def scheduled_runs(self)->list[dict[str,Any]]:
        workflow=urllib.parse.quote(WORKFLOW_FILE,safe="")
        rows=self.json(f"/repos/{self.repository}/actions/workflows/{workflow}/runs?event=schedule&per_page=100").get("workflow_runs",[])
        if not isinstance(rows,list): raise ActionsEvidenceError("workflow_runs must be an array")
        return rows
    def run_artifacts(self,run_id:str)->list[dict[str,Any]]:
        rows=self.json(f"/repos/{self.repository}/actions/runs/{run_id}/artifacts?per_page=100").get("artifacts",[])
        if not isinstance(rows,list): raise ActionsEvidenceError("artifacts must be an array")
        return rows
    def download_artifact(self,artifact_id:int)->bytes: return self.request(f"/repos/{self.repository}/actions/artifacts/{artifact_id}/zip")

def collect_run(client:GitHubActionsClient,run:dict[str,Any])->dict[str,Any]|None:
    if run.get("event")!="schedule" or run.get("status")!="completed" or run.get("conclusion")!="success": return None
    run_id=str(run.get("id")); artifact=select_artifact(client.run_artifacts(run_id),run_id=run_id)
    if artifact is None: return None
    return prediction_payload_from_zip(client.download_artifact(int(artifact["id"])),run_id=run_id,run_attempt=int(run.get("run_attempt",0)),head_sha=str(run.get("head_sha","")))
