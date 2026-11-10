"""Server-side Google OAuth 2.0 — authorization-code flow with PKCE + state.

Kept deliberately small and dependency-free (standard library only) so it adds a
"Sign in with Google" option next to the existing username/password login without
pulling new runtime packages — fresh installs and the offline test suite keep
working. Configuration is read from the environment, never hardcoded:

    GOOGLE_CLIENT_ID       the OAuth client id (public)
    GOOGLE_CLIENT_SECRET   the OAuth client secret (secret; from service.env)
    ALLOWED_GOOGLE_EMAILS  comma-separated allowlist of verified emails that may log in
    PUBLIC_BASE_URL        the public https origin, used to build the exact redirect_uri
                           registered in Google Cloud (falls back to proxy headers)
"""
import base64
import hashlib
import json
import os
import urllib.parse
import urllib.request

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"
_UA = "credit-scanner-oauth"


def client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def enabled() -> bool:
    """Show the Google button only when a client id and secret are configured."""
    return bool(client_id() and client_secret())


def allowed_emails() -> set:
    raw = os.environ.get("ALLOWED_GOOGLE_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def public_base_url(request) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base:
        return base
    # Fall back to the public host/proto seen through the reverse proxy, not the
    # internal http host uvicorn binds to.
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def redirect_uri(request) -> str:
    return public_base_url(request) + "/auth/google/callback"


def pkce_pair():
    """Return (code_verifier, code_challenge) for PKCE S256."""
    import secrets
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(state: str, code_challenge: str, redirect: str) -> str:
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
    }
    return AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def exchange_code(code: str, code_verifier: str, redirect: str) -> dict:
    return _post_form(TOKEN_ENDPOINT, {
        "code": code,
        "client_id": client_id(),
        "client_secret": client_secret(),
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    })


def fetch_userinfo(access_token: str) -> dict:
    req = urllib.request.Request(
        USERINFO_ENDPOINT,
        headers={"Authorization": "Bearer " + access_token, "Accept": "application/json", "User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())
