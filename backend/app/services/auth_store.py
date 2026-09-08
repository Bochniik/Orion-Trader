import hashlib
import hmac
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock


class AuthStore:
    def __init__(self, database_path=None, data_root=None):
        backend_root = Path(__file__).resolve().parents[2]
        self.data_root = Path(data_root or backend_root / "data")
        self.database_path = Path(database_path or self.data_root / "platform.db")
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)")

    @staticmethod
    def _password_hash(password, salt=None):
        if len(password) < 12 or len(password) > 256:
            raise ValueError("Password must be between 12 and 256 characters")
        salt = salt or secrets.token_bytes(16)
        derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"

    @classmethod
    def _verify_password(cls, password, encoded):
        try:
            _, n, r, p, salt, expected = encoded.split("$")
            derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
            return hmac.compare_digest(derived.hex(), expected)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _email(email):
        clean = str(email or "").strip().lower()
        if len(clean) > 254 or "@" not in clean or clean.startswith("@") or clean.endswith("@"):
            raise ValueError("A valid email address is required")
        return clean

    def register(self, email, password):
        clean_email = self._email(email)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if user_count and os.getenv("ORION_ALLOW_REGISTRATION", "true").lower() != "true":
                raise ValueError("Registration is disabled")
            user_id = str(uuid.uuid4())
            try:
                connection.execute("INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)", (user_id, clean_email, self._password_hash(password)))
            except sqlite3.IntegrityError as exc:
                raise ValueError("An account with that email already exists") from exc
        try:
            self._provision_user_database(user_id, claim_legacy=user_count == 0)
        except Exception:
            with self._connect() as connection:
                connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            raise
        return self.create_session(user_id)

    def login(self, email, password):
        with self._connect() as connection:
            row = connection.execute("SELECT id, password_hash FROM users WHERE email = ?", (self._email(email),)).fetchone()
        if row is None:
            # Spend comparable work for unknown users to reduce timing-based
            # email enumeration through the login endpoint.
            self._password_hash(password)
            raise ValueError("Invalid email or password")
        if not self._verify_password(password, row["password_hash"]):
            raise ValueError("Invalid email or password")
        return self.create_session(row["id"])

    def create_session(self, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
            connection.execute("INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, expires.isoformat()))
            user = connection.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"token": token, "csrf_token": csrf, "expires_at": expires.isoformat(), "user": dict(user)}

    def authenticate(self, token):
        if not token:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT s.user_id, s.csrf_token, s.expires_at, u.email, u.created_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            return None
        return {"user": {"id": row["user_id"], "email": row["email"], "created_at": row["created_at"]}, "csrf_token": row["csrf_token"], "expires_at": row["expires_at"]}

    def logout(self, token):
        if token:
            with self._connect() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))

    def user_database(self, user_id):
        return self.data_root / "users" / user_id / "orion.db"

    def _provision_user_database(self, user_id, claim_legacy=False):
        target = self.user_database(user_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy = self.data_root / "orion.db"
        if claim_legacy and legacy.exists() and not target.exists():
            # SQLite's backup API includes committed WAL content; a raw file
            # copy could silently omit recent transactions.
            with sqlite3.connect(legacy) as source, sqlite3.connect(target) as destination:
                source.backup(destination)
