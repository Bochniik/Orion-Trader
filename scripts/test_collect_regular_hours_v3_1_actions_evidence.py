import io, json, zipfile
from scripts.collect_regular_hours_v3_1_actions_evidence import ActionsEvidenceError, WORKFLOW_FILE, prediction_payload_from_zip, select_artifact

SHA = "a" * 40

def blob(payload, name="prediction-42.json"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(name, json.dumps(payload))
    return out.getvalue()

def payload(**overrides):
    provenance = {"workflow_run_id": 42, "run_attempt": 1, "github_head_sha": SHA, "event_name": "schedule", "forward_eligible": True}
    provenance.update(overrides)
    return {"acquisition_provenance": provenance}

def must_fail(fn):
    try:
        fn()
    except ActionsEvidenceError:
        return
    raise AssertionError("expected ActionsEvidenceError")

def main():
    assert WORKFLOW_FILE == "market-acquisition-scheduler.yml"
    assert select_artifact([{"name": "regular-hours-v3-1-shadow-42", "expired": False}], run_id="42") is not None
    assert select_artifact([{"name": "regular-hours-v3-1-shadow-42", "expired": True}], run_id="42") is None
    assert prediction_payload_from_zip(blob(payload()), run_id="42", run_attempt=1, head_sha=SHA)["acquisition_provenance"]["workflow_run_id"] == 42
    must_fail(lambda: prediction_payload_from_zip(blob(payload(workflow_run_id=99)), run_id="42", run_attempt=1, head_sha=SHA))
    must_fail(lambda: prediction_payload_from_zip(blob(payload(run_attempt=2)), run_id="42", run_attempt=1, head_sha=SHA))
    must_fail(lambda: prediction_payload_from_zip(blob(payload(github_head_sha="b" * 40)), run_id="42", run_attempt=1, head_sha=SHA))
    must_fail(lambda: prediction_payload_from_zip(blob(payload(forward_eligible=False)), run_id="42", run_attempt=1, head_sha=SHA))
    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../prediction-42.json", json.dumps(payload()))
    must_fail(lambda: prediction_payload_from_zip(unsafe.getvalue(), run_id="42", run_attempt=1, head_sha=SHA))
    print("regular-hours Actions collector tests passed")

if __name__ == "__main__":
    main()
