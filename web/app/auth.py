"""Accounts: one owner (full control) and any number of read-only viewers."""
import base64
import hashlib
import hmac
import secrets
import time

from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import db

SESSION_COOKIE = "cdash_session"
SESSION_MAX_AGE = 14 * 24 * 3600
OAUTH_COOKIE = "cdash_oauth"
OAUTH_MAX_AGE = 600  # 10 minutes to complete the Google round-trip
_fails: dict = {}


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(db.secret_file("session_secret"), salt="cdash")


def make_session(user_id: int) -> str:
    return serializer().dumps({"uid": user_id, "csrf": secrets.token_urlsafe(16)})


def oauth_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(db.secret_file("session_secret"), salt="cdash-oauth")


def make_oauth_state(data: dict) -> str:
    """Sign the transient state + PKCE verifier + next URL for the Google round-trip."""
    return oauth_serializer().dumps(data)


def read_oauth_state(token: str):
    if not token:
        return None
    try:
        return oauth_serializer().loads(token, max_age=OAUTH_MAX_AGE)
    except BadSignature:
        return None


def read_session(token: str):
    if not token:
        return None
    try:
        return serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


def current_user(con, token: str):
    s = read_session(token)
    if not s:
        return None
    row = con.execute("SELECT id, username, role FROM users WHERE id = ?", (s["uid"],)).fetchone()
    if not row:
        return None
    u = dict(row)
    u["csrf"] = s["csrf"]
    return u


def has_owner(con) -> bool:
    return con.execute("SELECT 1 FROM users WHERE role = 'owner'").fetchone() is not None


def setup_token() -> str:
    """One-time token needed to create the owner account (shown by run.sh / `python -m app.cli setup-link`)."""
    return db.secret_file("setup_token", 24)


def check_setup_token(token: str) -> bool:
    return bool(token) and hmac.compare_digest(token, setup_token())


def burn_setup_token() -> None:
    p = db.DATA_DIR / "setup_token"
    if p.exists():
        p.unlink()


def rate_limited(key: str) -> bool:
    """Allow 8 failed logins per 15 minutes per client."""
    now = time.time()
    fails = [t for t in _fails.get(key, []) if now - t < 900]
    _fails[key] = fails
    return len(fails) >= 8


def record_fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


def generate_password() -> str:
    return "-".join(secrets.token_urlsafe(4) for _ in range(3))
