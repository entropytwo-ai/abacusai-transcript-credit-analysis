"""Report data: the same numbers credit-scanner.sh prints, built from the database."""
import json
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import briefs, db

_UTC = timezone.utc


def _zone(con):
    name = (db.get_setting(con, "display_tz") or "America/New_York").strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("America/New_York")


def local_dt(iso: str, zone):
    """Parse a stored ISO timestamp (UTC) and return it as an aware datetime in `zone`."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(zone)


def local_date(iso: str, zone) -> str:
    """Date (YYYY-MM-DD) of a stored UTC timestamp, in the display timezone."""
    dt = local_dt(iso, zone)
    return dt.strftime("%Y-%m-%d") if dt else ""


def human_size(n: int) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def mode_smallest(values):
    """Most common value; ties go to the smallest (same rule as credit-scanner.sh)."""
    if not values:
        return 0
    c = Counter(values)
    top = max(c.values())
    return min(v for v, n in c.items() if n == top)


def settings(con) -> dict:
    return {"rate": float(db.get_setting(con, "rate_usd_per_10k") or 10),
            "tpw": float(db.get_setting(con, "tokens_per_word") or 1.33)}


def est_tokens(words: int, tpw: float) -> int:
    return int(words * tpw + 0.5)


def usd(credits: float, rate: float) -> float:
    return credits * rate / 10000.0


def projects(con, sort: str = "credits-desc") -> list:
    s = settings(con)
    zone = _zone(con)
    rows = con.execute("""
        SELECT p.id, p.slug, p.name, p.extra,
               COUNT(DISTINCT c.id)              AS chats,
               MIN(c.created_at)                 AS created,
               MAX(COALESCE(t.bot_ts, c.last_event_at)) AS last_activity,
               COUNT(t.message_index)            AS turns,
               COALESCE(SUM(t.words), 0)         AS words,
               COALESCE(SUM(t.text_bytes), 0)    AS text_bytes,
               COALESCE(SUM(t.credits), 0)       AS credits,
               COALESCE(SUM(t.runtime_secs), 0)  AS runtime_secs
        FROM projects p
        JOIN conversations c ON c.project_id = p.id AND c.excluded = 0
        LEFT JOIN turns t ON t.conversation_id = c.id
        GROUP BY p.id""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["credits_i"] = int(round(d["credits"]))
        d["tokens"] = est_tokens(d["words"], s["tpw"])
        d["usd"] = usd(d["credits_i"], s["rate"])
        d["size_h"] = human_size(d["text_bytes"])
        d["created_date"] = local_date(d["created"], zone)
        d["last_date"] = local_date(d["last_activity"], zone)
        d["extra"] = json.loads(d["extra"] or "{}")
        out.append(d)
    keys = {
        "name": (lambda d: d["name"].lower(), False), "credits-desc": (lambda d: d["credits"], True),
        "credits-asc": (lambda d: d["credits"], False), "created": (lambda d: d["created"] or "", False),
        "created-desc": (lambda d: d["created"] or "", True), "words": (lambda d: d["words"], True),
        "size": (lambda d: d["text_bytes"], True),
    }
    key, rev = keys.get(sort, keys["credits-desc"])
    out.sort(key=key, reverse=rev)
    return out


def totals(rows: list, con) -> dict:
    s = settings(con)
    credits = sum(r["credits_i"] for r in rows)
    words = sum(r["words"] for r in rows)
    return {"files": len(rows), "credits": credits, "usd": usd(credits, s["rate"]), "words": words,
            "tokens": sum(r["tokens"] for r in rows), "text_bytes": sum(r["text_bytes"] for r in rows),
            "size_h": human_size(sum(r["text_bytes"] for r in rows)), "chats": sum(r["chats"] for r in rows),
            "turns": sum(r["turns"] for r in rows), "runtime_secs": sum(r["runtime_secs"] for r in rows)}


def statistics(rows: list, con) -> dict:
    """Total / Mean / Median / Mode for credits, USD, words and est. tokens across projects."""
    s = settings(con)
    n = len(rows)
    cols = {"credits": [r["credits_i"] for r in rows], "words": [r["words"] for r in rows],
            "tokens": [r["tokens"] for r in rows], "turns": [r["turns"] for r in rows],
            "runtime": [r["runtime_secs"] for r in rows]}
    res = {"n": n}
    for k, v in cols.items():
        res[k] = {"total": sum(v), "mean": (sum(v) / n) if n else 0, "median": median(v) if n else 0,
                  "mode": mode_smallest(v)}
    res["usd"] = {k: usd(res["credits"][k], s["rate"]) for k in ("total", "mean", "median", "mode")}
    return res


def project_turns(con, project_id: int) -> list:
    s = settings(con)
    zone = _zone(con)
    terms = db.redact_terms(con)
    rows = con.execute("""
        SELECT t.*, c.name AS chat_name FROM turns t JOIN conversations c ON c.id = t.conversation_id
        WHERE c.project_id = ? AND c.excluded = 0 ORDER BY COALESCE(t.bot_ts, t.user_ts), t.message_index""",
                       (project_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tokens"] = est_tokens(d["words"], s["tpw"])
        d["credits_i"] = int(round(d["credits"]))
        d["usd"] = usd(d["credits"], s["rate"])
        d["date"] = local_date(d["bot_ts"] or d["user_ts"], zone)
        _ts = local_dt(d["user_ts"] or d["bot_ts"], zone)
        d["time"] = _ts.strftime("%H:%M") if _ts else ""
        d["attachments"] = [briefs.scrub(a, terms) for a in json.loads(d["attachments"] or "[]")]
        out.append(d)
    return out


def daily(con) -> list:
    """Credits per day (in the display timezone) across included chats (for the chart)."""
    zone = _zone(con)
    rows = con.execute("""
        SELECT t.bot_ts AS bot_ts, t.credits AS credits FROM turns t
        JOIN conversations c ON c.id = t.conversation_id
        WHERE c.excluded = 0 AND c.project_id IS NOT NULL AND t.bot_ts != ''""").fetchall()
    agg = Counter()
    for r in rows:
        day = local_date(r["bot_ts"], zone)
        if day:
            agg[day] += r["credits"] or 0
    return [{"day": day, "credits": agg[day]} for day in sorted(agg)]
