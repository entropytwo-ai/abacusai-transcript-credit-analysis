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


def tz_label(con) -> str:
    """Short current abbreviation of the display timezone, e.g. 'EST' / 'EDT'."""
    return datetime.now(_zone(con)).strftime("%Z") or "local"


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
        d["repo_url"] = (d["extra"].get("repo_url") or "").strip()
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


def cost_history(con) -> dict:
    """Cost per 10,000 credits over time, as ready-to-render SVG geometry.

    The line slopes between recorded changes (hills when the cost rises, valleys when it
    falls) and holds flat to today at the current cost. The current price "rides the line":
    a marker and a number sit on the line at today and move up or down whenever a new slope
    forms. Any pre-announced future changes (scheduled_rates) are drawn as a dashed slope
    projecting ahead to the new price on its effective date.
    """
    from datetime import date as _date, timedelta
    zone = _zone(con)
    rows = con.execute("SELECT changed_at, rate FROM rate_history ORDER BY changed_at, id").fetchall()
    pts = []
    for r in rows:
        d = local_date(r["changed_at"], zone)
        rate = float(r["rate"])
        if not d:
            continue
        if pts and pts[-1]["date"] == d:
            pts[-1]["rate"] = rate            # same day: keep the latest value
        else:
            pts.append({"date": d, "rate": rate})
    if not pts:
        return {}

    today = datetime.now(zone).date()
    cur = pts[-1]["rate"]
    # Pre-announced future changes (only those still ahead of today).
    sched = []
    for r in db.scheduled_rates(con, pending_only=True):
        try:
            sd = _date.fromisoformat(r["effective_date"])
        except (ValueError, TypeError):
            continue
        if sd > today:
            sched.append({"date": r["effective_date"], "rate": float(r["rate"]),
                          "note": (r["note"] or "")})
    sched.sort(key=lambda s: s["date"])

    first = _date.fromisoformat(pts[0]["date"])
    last = _date.fromisoformat(pts[-1]["date"])
    # Right edge of the time axis: the furthest scheduled change if any, else today.
    right_date = max([last, today] + [_date.fromisoformat(s["date"]) for s in sched])
    span = (right_date - first).days or 1

    W, H = 1000, 300
    PL, PR, PT, PB = 64, 24, 24, 44
    pw, ph = W - PL - PR, H - PT - PB
    ybot = PT + ph
    xr = W - PR                                  # right edge of the plot area
    all_rates = [p["rate"] for p in pts] + [s["rate"] for s in sched]
    top_val = (max(all_rates) * 1.25) or 1.0

    def X(d):
        return PL + (d - first).days / span * pw

    def Y(rate):
        return ybot - (rate / top_val) * ph

    # Where "now" sits on the x-axis. With no future schedule the line runs flat to the right
    # edge so the current price rides at the current moment; with a schedule, "now" is the
    # interior point today, and the dashed projection carries on to the right.
    now_x = X(today) if sched else float(xr)

    # Historical line: slope directly from point to point (hills up, valleys down), then hold
    # flat to "now" at the current cost.
    seg = ["M %.1f,%.1f" % (X(first), Y(pts[0]["rate"]))]
    for p in pts[1:]:
        seg.append("L %.1f,%.1f" % (X(_date.fromisoformat(p["date"])), Y(p["rate"])))
    seg.append("L %.1f,%.1f" % (now_x, Y(cur)))
    path = " ".join(seg)

    # Projected (dashed) line into the future toward each pre-announced change.
    proj = ""
    if sched:
        pseg = ["M %.1f,%.1f" % (now_x, Y(cur))]
        for s in sched:
            pseg.append("L %.1f,%.1f" % (X(_date.fromisoformat(s["date"])), Y(s["rate"])))
        proj = " ".join(pseg)

    dots = [{"x": round(X(_date.fromisoformat(p["date"])), 1), "y": round(Y(p["rate"]), 1),
             "date": p["date"], "rate": p["rate"]} for p in pts]
    sched_dots = [{"x": round(X(_date.fromisoformat(s["date"])), 1), "y": round(Y(s["rate"]), 1),
                   "date": s["date"], "rate": s["rate"], "note": s["note"]} for s in sched]
    ygrid = [{"y": round(ybot - f * ph, 1), "label": "$%.2f" % (top_val * f)} for f in (0, .25, .5, .75, 1.0)]
    xlabels = [{"x": round(X(first), 1), "label": pts[0]["date"], "anchor": "start"},
               {"x": round(float(xr), 1), "label": right_date.isoformat(), "anchor": "end"}]

    # The current price rides the line at "now": a marker + number on the line itself.
    ry = Y(cur)
    near_right = now_x > PL + pw * 0.55
    rider = {"x": round(now_x, 1), "y": round(ry, 1), "rate": cur,
             "lx": round(now_x + (-9 if near_right else 9), 1),
             "ly": round(min(ybot - 4, max(PT + 14, ry - 12)), 1),
             "anchor": "end" if near_right else "start"}
    today_x = round(X(today), 1)

    base = pts[0]["rate"]
    return {"path": path, "proj": proj, "dots": dots, "sched_dots": sched_dots,
            "ygrid": ygrid, "xlabels": xlabels, "rider": rider, "today_x": today_x,
            "w": W, "h": H, "current": cur, "first": base, "has_proj": bool(sched),
            "inflation_pct": ((cur - base) / base * 100) if base else 0.0,
            "changes": len(pts) - 1}


def rate_schedule(con) -> list:
    """Sorted [(local_date, rate)] of recorded cost changes, for time-accurate valuation."""
    zone = _zone(con)
    rows = con.execute("SELECT changed_at, rate FROM rate_history ORDER BY changed_at, id").fetchall()
    sched: list = []
    for r in rows:
        d = local_date(r["changed_at"], zone)
        if not d:
            continue
        rate = float(r["rate"])
        if sched and sched[-1][0] == d:
            sched[-1] = (d, rate)            # same day: the latest value wins
        else:
            sched.append((d, rate))
    return sched


def _rate_at(sched: list, day: str, current: float) -> float:
    """Cost per 10,000 credits in effect on local date `day`.

    Usage before the first recorded cost is valued at that first cost (we have no earlier
    price); usage on/after a change takes the changed cost.
    """
    if not sched or not day:
        return current
    rate = sched[0][1]
    for d, r in sched:
        if d <= day:
            rate = r
        else:
            break
    return rate


def valuation(con, rows: list) -> dict:
    """Time-accurate ("as incurred") USD valuation beside the flat current-rate one.

    Each turn's credits are valued at the cost per 10,000 credits that was in effect on the
    day it happened, so old usage keeps its old price and new usage the new price — a
    blended, dollar-cost-average view. Adds ``usd_asincurred`` and ``usd_delta`` to each row
    (``usd_delta`` = today's-rate value minus as-incurred value) and returns the totals.
    """
    s = settings(con)
    cur = s["rate"]
    sched = rate_schedule(con)
    if len({r for _, r in sched}) <= 1:            # only a baseline: nothing to blend yet
        for row in rows:
            row["usd_asincurred"] = row["usd"]
            row["usd_delta"] = 0.0
        tc = sum(row["usd"] for row in rows)
        return {"current_rate": cur, "blended_rate": cur, "usd_current": tc,
                "usd_asincurred": tc, "delta": 0.0, "has_changes": False}
    zone = _zone(con)
    per: dict = {}
    for r in con.execute(
            "SELECT c.project_id AS pid, t.bot_ts AS bot_ts, t.credits AS credits "
            "FROM turns t JOIN conversations c ON c.id = t.conversation_id "
            "WHERE c.excluded = 0 AND c.project_id IS NOT NULL").fetchall():
        rate = _rate_at(sched, local_date(r["bot_ts"], zone), cur)
        per[r["pid"]] = per.get(r["pid"], 0.0) + (r["credits"] or 0) * rate / 10000.0
    for row in rows:
        ai = per.get(row["id"], 0.0)
        row["usd_asincurred"] = ai
        row["usd_delta"] = row["usd"] - ai
    tc = sum(row["usd"] for row in rows)
    ta = sum(row["usd_asincurred"] for row in rows)
    credits = sum(row["credits_i"] for row in rows)
    return {"current_rate": cur, "blended_rate": (ta / credits * 10000.0) if credits else cur,
            "usd_current": tc, "usd_asincurred": ta, "delta": tc - ta, "has_changes": True}


def active_times(con, project_id: int | None = None) -> list:
    """Per-day list of turn start-times (display timezone) for the activity scatter chart.

    Each turn is placed by when the user sent the prompt (``user_ts``), falling back to
    the agent's reply time. ``frac`` is the position down a 24h axis (0.0 = 00:00 top,
    1.0 = 24:00 bottom); ``label`` is HH:MM for the hover tooltip.
    """
    zone = _zone(con)
    sql = ("SELECT t.user_ts AS user_ts, t.bot_ts AS bot_ts FROM turns t "
           "JOIN conversations c ON c.id = t.conversation_id "
           "WHERE c.excluded = 0 AND c.project_id IS NOT NULL")
    params: list = []
    if project_id is not None:
        sql += " AND c.project_id = ?"
        params.append(project_id)
    byday: dict = {}
    for r in con.execute(sql, params).fetchall():
        dt = local_dt(r["user_ts"] or r["bot_ts"], zone)
        if not dt:
            continue
        minutes = dt.hour * 60 + dt.minute
        byday.setdefault(dt.strftime("%Y-%m-%d"), []).append(
            {"frac": minutes / 1440.0, "label": dt.strftime("%H:%M")})
    out = []
    for day in sorted(byday):
        dots = sorted(byday[day], key=lambda d: d["frac"])
        out.append({"day": day, "dots": dots, "count": len(dots)})
    return out
