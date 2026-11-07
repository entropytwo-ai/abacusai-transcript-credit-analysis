"""Import agent chats from the Abacus.AI API into SQLite.

* Lists every SUPER_AGENT (Abacus AI Agent) conversation.
* Re-downloads a conversation only when it has new events.
* One turn per agent reply: the user's prompt + the agent's visible reply text +
  `compute_points_used` (the "Credits: N" shown under each reply).
* New chats are grouped into a project automatically (see `auto_project`).
* Briefs are generated only for turns that are new or changed.
"""
import datetime as dt
import gzip
import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from . import briefs, db

log = logging.getLogger("sync")
CONVERSATION_TYPE = "SUPER_AGENT"
BRIEF_BATCH = 6

_state = {"running": False, "last_error": None}
_run_lock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def word_count(text: str) -> int:
    return len((text or "").split())


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "project"


def base_name(name: str) -> str:
    """'2-Linux Dotfiles Setup' / 'xtree dev (part 3)' -> 'linux dotfiles setup' / 'xtree dev'."""
    n = (name or "").strip().lower()
    n = re.sub(r"^(?:part\s*)?\d+\s*[-_.:)]\s*", "", n)
    n = re.sub(r"\s*[-_(]\s*(?:part\s*)?\d+\)?$", "", n)
    n = re.sub(r"\s*\.\.\.$|…$", "", n)
    return re.sub(r"\s+", " ", n).strip()


# ---------------------------------------------------------------- parsing
def agent_visible_text(segments) -> str:
    """Only the reply text the user sees (not thoughts, tool calls or tool output)."""
    parts, gap = [], False
    for s in segments or []:
        if isinstance(s, dict) and s.get("type") == "text":
            seg = s.get("segment")
            if isinstance(seg, str) and seg:
                if gap and parts and not parts[-1].endswith(("\n", " ")):
                    parts.append("\n\n")
                parts.append(seg)
                gap = False
        else:
            gap = True       # a tool call / thought block sits between two text blocks
    return "".join(parts).strip()


def _attachments(msg) -> list:
    names = []
    for key in ("attachments", "attached_files", "docInfos", "doc_infos"):
        for a in _get(msg, key) or []:
            n = _get(a, "name") or _get(a, "filename") or _get(a, "file_name")
            if n:
                names.append(str(n))
    return names


def parse_turns(history) -> list:
    """Pair each BOT message with the USER message(s) before it."""
    turns, pending_user, user_ts, atts = [], [], None, []
    for m in history or []:
        role = _get(m, "role")
        if role == "USER":
            if _get(m, "text"):
                pending_user.append(_get(m, "text"))
            user_ts = user_ts or _get(m, "timestamp")
            atts += _attachments(m)
        elif role == "BOT":
            user_text = "\n\n".join(pending_user)
            agent_text = agent_visible_text(_get(m, "segments")) or (_get(m, "text") or "")
            credits = float(_get(m, "compute_points_used") or 0)
            if user_text or agent_text or credits:
                text = user_text + "\n" + agent_text
                turns.append({
                    "message_index": int(_get(m, "message_index") or len(turns)),
                    "user_ts": str(user_ts or _get(m, "timestamp") or ""),
                    "bot_ts": str(_get(m, "timestamp") or ""),
                    "user_text": user_text,
                    "agent_text": agent_text,
                    "attachments": json.dumps(atts),
                    "credits": credits,
                    "runtime_secs": float(_get(m, "turn_runtime_secs")) if _get(m, "turn_runtime_secs") else None,
                    "words": word_count(user_text) + word_count(agent_text),
                    "text_bytes": len(text.encode("utf-8")),
                    "text_hash": hashlib.sha1(text.encode("utf-8")).hexdigest(),
                    "extra": json.dumps({k: _get(m, k) for k in ("deepagent_mode", "model_version", "regenerate_attempt")
                                         if _get(m, k) is not None}, default=str),
                })
            pending_user, user_ts, atts = [], None, []
    return turns


# ---------------------------------------------------------------- grouping
def auto_project(con, conv_id: str, name: str) -> int:
    """Put a new chat in the project of an existing chat with the same base name, else a new project."""
    b = base_name(name)
    for row in con.execute("SELECT name, project_id FROM conversations WHERE project_id IS NOT NULL AND id != ?", (conv_id,)):
        if base_name(row["name"]) == b and b:
            return row["project_id"]
    slug = slugify(b or name)
    row = con.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute("INSERT INTO projects(slug, name) VALUES (?, ?)", (slug, slug))
    return cur.lastrowid


def apply_seed(con, seed: dict) -> None:
    """Optional local seed (data/projects-seed.json): {"projects": {slug: [conv_ids]}, "excluded": [conv_ids],
    "redact_terms": [...]}. Applied only to chats that are not yet assigned, so edits made in the UI win."""
    for slug, ids in (seed.get("projects") or {}).items():
        row = con.execute("SELECT id FROM projects WHERE slug = ?", (slugify(slug),)).fetchone()
        pid = row["id"] if row else con.execute("INSERT INTO projects(slug, name) VALUES (?, ?)",
                                                (slugify(slug), slug)).lastrowid
        for cid in ids:
            con.execute("INSERT OR IGNORE INTO conversations(id, name, project_id) VALUES (?, ?, ?)", (cid, cid, pid))
    for cid in seed.get("excluded") or []:
        con.execute("INSERT OR IGNORE INTO conversations(id, name, excluded) VALUES (?, ?, 1)", (cid, cid))
    if seed.get("redact_terms") and not db.redact_terms(con):
        db.set_setting(con, "redact_terms", json.dumps(seed["redact_terms"]))


def load_seed(con) -> None:
    p = db.DATA_DIR / "projects-seed.json"
    if p.exists():
        apply_seed(con, json.loads(p.read_text()))
        p.rename(p.with_suffix(".json.applied"))


# ---------------------------------------------------------------- sync
def store_conversation(con, conv: dict) -> int:
    """Upsert one full conversation (dict from the API). Returns number of turns stored."""
    cid = conv["deployment_conversation_id"]
    name = conv.get("name") or cid
    row = con.execute("SELECT project_id, excluded FROM conversations WHERE id = ?", (cid,)).fetchone()
    if row is None:
        con.execute("INSERT INTO conversations(id, name) VALUES (?, ?)", (cid, name))
        pid = auto_project(con, cid, name)
    else:
        pid = row["project_id"]
        if pid is None and not row["excluded"]:
            pid = auto_project(con, cid, name)
    raw = gzip.compress(json.dumps(conv, default=str).encode("utf-8"))
    con.execute("""UPDATE conversations SET name=?, project_id=?, created_at=?, last_event_at=?, conversation_type=?,
                   synced_event_at=?, synced_at=?, raw=? WHERE id=?""",
                (name, pid, str(conv.get("created_at") or ""), str(conv.get("last_event_created_at") or ""),
                 conv.get("conversation_type"), str(conv.get("last_event_created_at") or ""), now(), raw, cid))
    turns = parse_turns(conv.get("history"))
    keep = [t["message_index"] for t in turns]
    con.execute(f"DELETE FROM turns WHERE conversation_id = ? AND message_index NOT IN ({','.join('?' * len(keep)) or 'NULL'})",
                [cid] + keep)
    for t in turns:
        con.execute("""INSERT INTO turns(conversation_id, message_index, user_ts, bot_ts, user_text, agent_text, attachments,
                         credits, runtime_secs, words, text_bytes, text_hash, extra)
                       VALUES (:cid, :message_index, :user_ts, :bot_ts, :user_text, :agent_text, :attachments,
                         :credits, :runtime_secs, :words, :text_bytes, :text_hash, :extra)
                       ON CONFLICT(conversation_id, message_index) DO UPDATE SET
                         user_ts=excluded.user_ts, bot_ts=excluded.bot_ts, user_text=excluded.user_text,
                         agent_text=excluded.agent_text, attachments=excluded.attachments, credits=excluded.credits,
                         runtime_secs=excluded.runtime_secs, words=excluded.words, text_bytes=excluded.text_bytes,
                         text_hash=excluded.text_hash, extra=excluded.extra""", dict(t, cid=cid))
    return len(turns)


def make_briefs(con, client, limit=None) -> dict:
    """Fill in briefs for turns that have none or whose text changed."""
    terms = db.redact_terms(con)
    model = db.get_setting(con, "brief_llm")
    rows = con.execute("""SELECT t.conversation_id, t.message_index, t.user_text, t.agent_text, t.text_hash FROM turns t
                          JOIN conversations c ON c.id = t.conversation_id AND c.excluded = 0
                          WHERE t.brief_hash IS NULL OR t.brief_hash != t.text_hash
                          ORDER BY t.conversation_id, t.message_index""").fetchall()
    if limit:
        rows = rows[:limit]
    items = [{"id": f"{r['conversation_id']}:{r['message_index']}", "user_text": r["user_text"],
              "agent_text": r["agent_text"], "hash": r["text_hash"]} for r in rows]
    batches = [items[i:i + BRIEF_BATCH] for i in range(0, len(items), BRIEF_BATCH)]
    stats = {"llm": 0, "fallback": 0}

    def run(batch):
        if client is None:
            return batch, {}
        try:
            return batch, briefs.llm_briefs(client, model, batch, terms)
        except Exception as e:  # noqa: BLE001 - any LLM failure falls back to extracts
            log.warning("brief batch failed (%s); using fallback", e)
            return batch, {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        for batch, got in pool.map(run, batches):
            for it in batch:
                if it["id"] in got:
                    u, a = got[it["id"]]
                    src = f"llm:{model}"
                    stats["llm"] += 1
                else:
                    u, a = briefs.fallback(it["user_text"], it["agent_text"], terms)
                    src = "fallback"
                    stats["fallback"] += 1
                cid, idx = it["id"].rsplit(":", 1)
                con.execute("UPDATE turns SET user_brief=?, agent_brief=?, brief_hash=?, brief_source=? "
                            "WHERE conversation_id=? AND message_index=?", (u, a, it["hash"], src, cid, int(idx)))
            con.commit()
    return stats


def make_client():
    import abacusai  # imported lazily so the web UI works without it for tests
    return abacusai.ApiClient()


def run_sync(trigger: str = "manual", client=None, full: bool = False) -> dict:
    """Run one sync. Only one at a time; returns the stats dict."""
    if not _run_lock.acquire(blocking=False):
        return {"status": "busy"}
    _state["running"] = True
    con = db.connect()
    run_id = con.execute("INSERT INTO sync_runs(started_at, trigger, status) VALUES (?, ?, 'running')",
                         (now(), trigger)).lastrowid
    con.commit()
    stats = {"listed": 0, "updated": 0, "turns": 0}
    try:
        load_seed(con)
        client = client or make_client()
        convs = client.list_deployment_conversations(conversation_type=CONVERSATION_TYPE, limit=10000)
        stats["listed"] = len(convs)
        for c in convs:
            cid = _get(c, "deployment_conversation_id")
            last = str(_get(c, "last_event_created_at") or "")
            row = con.execute("SELECT synced_event_at, excluded FROM conversations WHERE id = ?", (cid,)).fetchone()
            if row and row["synced_event_at"] == last and last and not full:
                continue
            full_conv = client.get_deployment_conversation(deployment_conversation_id=cid)
            d = full_conv.to_dict() if hasattr(full_conv, "to_dict") else dict(full_conv)
            d["last_event_created_at"] = d.get("last_event_created_at") or last
            stats["turns"] += store_conversation(con, d)
            con.execute("UPDATE conversations SET synced_event_at = ? WHERE id = ?", (last, cid))
            stats["updated"] += 1
            con.commit()
        stats["briefs"] = make_briefs(con, client)
        con.execute("UPDATE sync_runs SET finished_at=?, status='ok', stats=? WHERE id=?", (now(), json.dumps(stats), run_id))
        _state["last_error"] = None
    except Exception as e:  # noqa: BLE001
        log.exception("sync failed")
        _state["last_error"] = str(e)[:500]
        con.execute("UPDATE sync_runs SET finished_at=?, status='error', message=?, stats=? WHERE id=?",
                    (now(), str(e)[:500], json.dumps(stats), run_id))
        stats["status"] = "error"
        stats["error"] = str(e)[:500]
    finally:
        con.commit()
        con.close()
        _state["running"] = False
        _run_lock.release()
    return stats


def start_background(trigger="manual") -> bool:
    if _state["running"]:
        return False
    threading.Thread(target=run_sync, args=(trigger,), daemon=True).start()
    return True


def scheduler_loop(stop: threading.Event, interval: int = 600) -> None:
    """Once a day: sync when the last successful sync is from an earlier UTC day and the sync hour has passed."""
    stop.wait(5)
    while not stop.is_set():
        try:
            con = db.connect()
            hour = int(db.get_setting(con, "sync_hour_utc") or 8)
            last = con.execute("SELECT MAX(started_at) AS t FROM sync_runs WHERE status='ok'").fetchone()["t"]
            con.close()
            utc = dt.datetime.now(dt.timezone.utc)
            due = last is None or (last[:10] < utc.date().isoformat() and utc.hour >= hour)
            if due and not _state["running"]:
                run_sync("daily")
        except Exception:  # noqa: BLE001
            log.exception("scheduler error")
        stop.wait(interval)


def status() -> dict:
    con = db.connect()
    row = con.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    ok = con.execute("SELECT finished_at FROM sync_runs WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    return {"running": _state["running"],
            "last_run": dict(row) if row else None,
            "last_ok": ok["finished_at"] if ok else None}
