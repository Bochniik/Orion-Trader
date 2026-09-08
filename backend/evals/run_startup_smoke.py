"""Real-process, network-free startup and auth check against disposable data."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def main():
    app_source = Path(__file__).resolve().parents[1] / "app"
    with tempfile.TemporaryDirectory(prefix="orion-startup-") as directory:
        root = Path(directory)
        shutil.copytree(app_source, root / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {**os.environ, "ORION_AUTH_DISABLED": "false", "ORION_COOKIE_SECURE": "false"}
        with (root / "startup.log").open("w+") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=root, env=env, stdout=log, stderr=log)
            try:
                base = f"http://127.0.0.1:{port}"
                with httpx.Client(base_url=base, timeout=5, trust_env=False) as client:
                    for _ in range(60):
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.RequestError:
                            pass
                        if process.poll() is not None:
                            raise RuntimeError("Server exited during startup")
                        time.sleep(0.1)
                    health, ready = client.get("/health").json(), client.get("/ready").json()
                    assert health["status"] == "ok" and ready["status"] == "ready"
                    assert health["version"] == "2.4.0"
                    assert client.get("/core/status").status_code == 401
                    session = client.post("/auth/register", json={"email": "smoke@example.test", "password": "disposable-smoke-password"}).json()
                    assert client.post("/core/today").status_code == 403
                    headers = {"X-CSRF-Token": session["csrf_token"]}
                    assert client.post("/core/today", headers=headers).json()["status"] == "unavailable"
                    assert client.post("/core/jobs", json={"kind": "today"}).status_code == 403
                    job = client.post("/core/jobs", headers=headers, json={"kind": "today", "prepare": False}).json()
                    for _ in range(50):
                        receipt = client.get(f"/core/jobs/{job['id']}").json()
                        if receipt["state"] not in {"queued", "running"}:
                            break
                        time.sleep(.05)
                    assert receipt["state"] == "completed" and receipt["result"]["status"] == "unavailable"
                    assert client.get("/core/decisions").json()["decisions"] == []
                    assert client.post("/watchlist/ZZTEST", headers=headers).status_code == 200
                    assert "ZZTEST" in client.get("/watchlist").json()["tickers"]
                    assert client.post("/auth/logout", headers=headers).status_code == 200
                    assert client.get("/core/status").status_code == 401
                    client.post("/auth/register", json={"email": "second@example.test", "password": "disposable-smoke-password"})
                    assert "ZZTEST" not in client.get("/watchlist").json()["tickers"]
                    assert client.get(f"/core/jobs/{job['id']}").status_code == 404
                    schema = client.get("/openapi.json").json()
                    assert all(path in schema["paths"] for path in ("/core/status", "/core/jobs", "/core/jobs/{job_id}", "/core/plans", "/core/decisions", "/candles/{ticker}", "/watchlist"))
                    print(json.dumps({"health": health["status"], "ready": ready["status"], "version": health["version"], "api_paths": len(schema["paths"]), "auth_csrf_isolation": "passed", "user_data": "disposable_only"}, indent=2))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
