"""Package source only, excluding all credentials, user data and build caches."""
import argparse
import hashlib
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing release archive; choose a new output path.")
    excluded = {"node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".git", "data", ".venv", "venv", "coverage", "test-results", "playwright-report"}
    folders = {"backend", "frontend", "docs", "scripts", ".github"}
    root_extensions = {".md", ".txt", ".ps1", ".cmd", ".ico", ".yml"}
    special = {".gitignore", ".dockerignore", ".env.example", "Lessons_Learned"}
    paths = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in excluded or part.startswith(".venv") for part in relative.parts):
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.suffix in {".db", ".sqlite", ".sqlite3", ".pyc", ".log", ".zip"} or path.name.endswith((".db-wal", ".db-shm")):
            continue
        if len(relative.parts) > 1 and relative.parts[0] not in folders:
            continue
        if len(relative.parts) == 1 and path.suffix not in root_extensions and path.name not in special:
            continue
        paths.append(path)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(paths):
            archive.write(path, Path("OrionTrader") / path.relative_to(root))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert "OrionTrader/backend/app/api/core_routes.py" in names
        assert "OrionTrader/frontend/src/core/CoreApp.jsx" in names
        assert "OrionTrader/frontend/vite.config.js" in names
        assert "OrionTrader/frontend/package-lock.json" in names
    with output.open("rb") as archive_bytes:
        digest = hashlib.file_digest(archive_bytes, "sha256").hexdigest()
    print(f"{output}\nFiles: {len(paths)}\nBytes: {output.stat().st_size}\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
