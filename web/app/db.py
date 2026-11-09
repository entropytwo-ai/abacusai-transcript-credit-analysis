"""SQLite storage. One file, created and migrated automatically on startup."""
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("CREDIT_DASH_DATA", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "credits.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id            INTEGER PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    notes         TEXT DEFAULT '',
    extra         TEXT DEFAULT '{}'          -- free-form JSON for future metadata
);
CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,         -- Abacus.AI deployment_conversation_id
    name            TEXT NOT NULL,
    project_id      INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    excluded        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT,
    last_event_at   TEXT,
    conversation_type TEXT,
    synced_event_at TEXT,                    -- last_event_at value we last imported
    synced_at       TEXT,
    raw             BLOB,                    -- gzip JSON of the full API response (for future metadata)
    extra           TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS turns (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_index   INTEGER NOT NULL,         -- index of the agent (BOT) message
    user_ts         TEXT,
    bot_ts          TEXT,
    user_text       TEXT DEFAULT '',
    agent_text      TEXT DEFAULT '',
    attachments     TEXT DEFAULT '[]',
    credits         REAL NOT NULL DEFAULT 0,
    runtime_secs    REAL,
    words           INTEGER NOT NULL DEFAULT 0,
    text_bytes      INTEGER NOT NULL DEFAULT 0,
    text_hash       TEXT,
    user_brief      TEXT,
    agent_brief     TEXT,
    brief_hash      TEXT,                     -- text_hash the briefs were made from
    brief_source    TEXT,                     -- 'llm:<model>' or 'fallback'
    extra           TEXT DEFAULT '{}',
    PRIMARY KEY (conversation_id, message_index)
);
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    username   TEXT UNIQUE NOT NULL COLLATE NOCASE,
    pw_hash    TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('owner', 'viewer')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    trigger     TEXT,
    status      TEXT,                         -- running | ok | error
    message     TEXT,
    stats       TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS rate_history (
    id         INTEGER PRIMARY KEY,
    changed_at TEXT NOT NULL,                 -- UTC ISO timestamp the cost took effect
    rate       REAL NOT NULL,                 -- USD per 10,000 credits
    source     TEXT NOT NULL DEFAULT 'settings' -- initial | settings | scheduled
);
CREATE TABLE IF NOT EXISTS scheduled_rates (
    id             INTEGER PRIMARY KEY,
    effective_date TEXT NOT NULL,             -- local (display tz) date YYYY-MM-DD the new cost starts
    rate           REAL NOT NULL,             -- USD per 10,000 credits
    note           TEXT DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at     TEXT                       -- set once promoted into rate_history
);
CREATE INDEX IF NOT EXISTS idx_turns_conv ON turns(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_project ON conversations(project_id);
"""

DEFAULT_SETTINGS = {
    "rate_usd_per_10k": "10",
    "tokens_per_word": "1.33",
    "brief_llm": "GEMINI_3_5_FLASH_LITE",
    "redact_terms": "[]",          # JSON list of extra words/names to scrub from excerpts
    "sync_hour_utc": "8",          # daily sync runs after this hour (UTC)
    "display_tz": "America/New_York",  # timezone for dates shown on the site (IANA name)
}

_lock = threading.RLock()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init() -> None:
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        # Seed the cost-history baseline so the "cost per 10,000 credits" chart has a
        # starting point. Later changes are appended automatically when the rate is saved.
        if not con.execute("SELECT 1 FROM rate_history LIMIT 1").fetchone():
            rate = float(con.execute("SELECT value FROM settings WHERE key='rate_usd_per_10k'").fetchone()["value"])
            con.execute("INSERT INTO rate_history(changed_at, rate, source) VALUES (datetime('now'), ?, 'initial')", (rate,))


def record_rate(con, rate: float, source: str = "settings") -> None:
    """Append a cost-per-10,000-credits data point only if it differs from the latest one."""
    last = con.execute("SELECT rate FROM rate_history ORDER BY changed_at DESC, id DESC LIMIT 1").fetchone()
    if last is None or abs(float(last["rate"]) - float(rate)) > 1e-9:
        con.execute("INSERT INTO rate_history(changed_at, rate, source) VALUES (datetime('now'), ?, ?)",
                    (float(rate), source))


def _rate_str(rate: float) -> str:
    """Compact text form of a rate for the settings value (no trailing zeros)."""
    return ("%.6f" % float(rate)).rstrip("0").rstrip(".") or "0"


def schedule_rate(con, effective_date: str, rate: float, note: str = "") -> None:
    """Record a future cost change (pre-announced to customers). effective_date is a local
    YYYY-MM-DD; it is applied automatically once that date arrives."""
    con.execute("INSERT INTO scheduled_rates(effective_date, rate, note) VALUES (?, ?, ?)",
                (effective_date, float(rate), (note or "").strip()))


def scheduled_rates(con, pending_only: bool = True) -> list:
    """Scheduled cost changes, soonest first. Pending = not yet applied."""
    q = "SELECT id, effective_date, rate, note, applied_at FROM scheduled_rates"
    if pending_only:
        q += " WHERE applied_at IS NULL"
    q += " ORDER BY effective_date, id"
    return con.execute(q).fetchall()


def delete_scheduled_rate(con, sid: int) -> None:
    con.execute("DELETE FROM scheduled_rates WHERE id = ? AND applied_at IS NULL", (int(sid),))


def apply_due_rates(con) -> int:
    """Promote any scheduled cost changes whose effective date has arrived: record them into
    rate_history (dated to the effective date) and make the latest the live rate. Returns the
    number applied. Safe and cheap to call on every page load."""
    from datetime import datetime, timezone
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(get_setting(con, "display_tz") or "UTC")
    except Exception:
        zone = timezone.utc
    today = datetime.now(zone).date().isoformat()
    due = con.execute("SELECT id, effective_date, rate FROM scheduled_rates "
                      "WHERE applied_at IS NULL AND effective_date <= ? ORDER BY effective_date, id",
                      (today,)).fetchall()
    applied = 0
    for row in due:
        # Date the change to local noon on its effective date, stored as UTC, so it maps back
        # to the same local date on the chart regardless of timezone offset.
        d = datetime.fromisoformat(row["effective_date"]).replace(hour=12, minute=0, second=0, tzinfo=zone)
        changed_at = d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        last = con.execute("SELECT rate FROM rate_history ORDER BY changed_at DESC, id DESC LIMIT 1").fetchone()
        if last is None or abs(float(last["rate"]) - float(row["rate"])) > 1e-9:
            con.execute("INSERT INTO rate_history(changed_at, rate, source) VALUES (?, ?, 'scheduled')",
                        (changed_at, float(row["rate"])))
        con.execute("UPDATE scheduled_rates SET applied_at = datetime('now') WHERE id = ?", (row["id"],))
        set_setting(con, "rate_usd_per_10k", _rate_str(row["rate"]))
        applied += 1
    if applied:
        con.commit()
    return applied


def get_setting(con, key: str) -> str:
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(con, key: str, value: str) -> None:
    con.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value))


def redact_terms(con) -> list:
    try:
        return [t for t in json.loads(get_setting(con, "redact_terms")) if isinstance(t, str) and t.strip()]
    except ValueError:
        return []


def secret_file(name: str, nbytes: int = 32) -> str:
    """Read (or create once) a random secret stored in the data dir with 0600 permissions."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = DATA_DIR / name
    if not p.exists():
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(nbytes))
    return p.read_text().strip()
