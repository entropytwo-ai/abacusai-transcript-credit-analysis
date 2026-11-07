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
CREATE INDEX IF NOT EXISTS idx_turns_conv ON turns(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_project ON conversations(project_id);
"""

DEFAULT_SETTINGS = {
    "rate_usd_per_10k": "10",
    "tokens_per_word": "1.33",
    "brief_llm": "GEMINI_3_5_FLASH_LITE",
    "redact_terms": "[]",          # JSON list of extra words/names to scrub from excerpts
    "sync_hour_utc": "8",          # daily sync runs after this hour (UTC)
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
