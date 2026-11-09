"""Abacus.AI credit dashboard: the credit-scanner report as a private website."""
import csv
import io
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db, pdf, report, sync

__version__ = "1.0.8"
HERE = Path(__file__).resolve().parent
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_stop = threading.Event()


@asynccontextmanager
async def lifespan(app):
    db.init()
    if os.environ.get("CREDIT_DASH_SCHEDULER", "1") == "1":
        threading.Thread(target=sync.scheduler_loop, args=(_stop,), daemon=True).start()
    yield
    _stop.set()


app = FastAPI(title="Abacus.AI Credit Dashboard", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["n0"] = lambda v: f"{int(round(v or 0)):,}"
templates.env.filters["n2"] = lambda v: f"{(v or 0):,.2f}"
templates.env.filters["money"] = lambda v: f"${(v or 0):,.2f}"
templates.env.filters["mins"] = lambda s: "<1" if 0 < (s or 0) < 60 else f"{(s or 0) / 60:,.0f}"


def _dur(s):
    """Human-readable duration from seconds: '2h 15m', '45m 03s', '12s', or '—' for none."""
    s = int(round(s or 0))
    if s <= 0:
        return "\u2014"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


templates.env.filters["dur"] = _dur


@app.middleware("http")
async def _cache_control(request: Request, call_next):
    """Never let a proxy/CDN cache dynamic pages: a cached response can drop the
    Set-Cookie on login/setup, which makes the submit buttons look dead (the form
    posts but the session cookie never sticks). Static assets are versioned, so
    they may be cached."""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "public, max-age=86400")
    else:
        resp.headers["Cache-Control"] = "no-store, private"
    return resp


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _login_redirect(request: Request, exc):
    return RedirectResponse("/login?next=" + request.url.path, status_code=303)


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def user_of(request: Request, con=Depends(get_con)):
    u = auth.current_user(con, request.cookies.get(auth.SESSION_COOKIE))
    if not u:
        raise LoginRequired()
    return u


def owner_of(user=Depends(user_of)):
    if user["role"] != "owner":
        raise HTTPException(403, "Owner only")
    return user


def check_csrf(user, token):
    if not token or token != user["csrf"]:
        raise HTTPException(400, "Bad form token, reload the page and try again")


def render(request, name, user=None, **ctx):
    return templates.TemplateResponse(request, name, {"user": user, "version": __version__, **ctx})


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https")


# ------------------------------------------------------------------ auth pages
@app.get("/healthz")
def healthz(con=Depends(get_con)):
    con.execute("SELECT 1")
    return {"ok": True, "version": __version__}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", con=Depends(get_con)):
    if not auth.has_owner(con):
        return render(request, "message.html", title="Not set up yet",
                      message="This dashboard has no owner account yet. Open the one-time setup link printed by run.sh.")
    return render(request, "login.html", next=next if next.startswith("/") else "/")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"),
          con=Depends(get_con)):
    key = request.client.host if request.client else "?"
    if auth.rate_limited(key):
        return render(request, "login.html", error="Too many attempts. Try again in 15 minutes.", next=next)
    row = con.execute("SELECT id, pw_hash FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if not row or not auth.verify_password(password, row["pw_hash"]):
        auth.record_fail(key)
        return render(request, "login.html", error="Wrong username or password.", next=next)
    resp = RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)
    resp.set_cookie(auth.SESSION_COOKIE, auth.make_session(row["id"]), max_age=auth.SESSION_MAX_AGE,
                    httponly=True, samesite="lax", secure=is_https(request))
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, token: str = "", con=Depends(get_con)):
    if auth.has_owner(con) or not auth.check_setup_token(token):
        return render(request, "message.html", title="Setup link not valid",
                      message="This setup link was already used or is wrong.")
    return render(request, "setup.html", token=token)


@app.post("/setup")
def setup(request: Request, token: str = Form(...), username: str = Form(...), password: str = Form(...),
          con=Depends(get_con)):
    if auth.has_owner(con) or not auth.check_setup_token(token):
        raise HTTPException(403, "Setup link not valid")
    if len(password) < 10 or not username.strip():
        return render(request, "setup.html", token=token, error="Use a username and a password of 10+ characters.")
    cur = con.execute("INSERT INTO users(username, pw_hash, role) VALUES (?, ?, 'owner')",
                      (username.strip(), auth.hash_password(password)))
    con.commit()
    auth.burn_setup_token()
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.SESSION_COOKIE, auth.make_session(cur.lastrowid), max_age=auth.SESSION_MAX_AGE,
                    httponly=True, samesite="lax", secure=is_https(request))
    return resp


# ------------------------------------------------------------------ reports
def _summary_ctx(con, sort):
    rows = report.projects(con, sort)
    return {"rows": rows, "total": report.totals(rows, con), "stats": report.statistics(rows, con),
            "settings": report.settings(con), "sync": sync.status(), "sort": sort}


@app.get("/", response_class=HTMLResponse)
def summary(request: Request, sort: str = "credits-desc", user=Depends(user_of), con=Depends(get_con)):
    ctx = _summary_ctx(con, sort)
    days = report.daily(con)
    ctx["daily"] = days
    ctx["daily_max"] = max((d["credits"] for d in days), default=0)
    ctx["activity"] = report.active_times(con)
    ctx["cost"] = report.cost_history(con)
    ctx["tz"] = report.tz_label(con)
    return render(request, "summary.html", user, **ctx)


@app.get("/project/{slug}", response_class=HTMLResponse)
def project(request: Request, slug: str, user=Depends(user_of), con=Depends(get_con)):
    p = next((r for r in report.projects(con) if r["slug"] == slug), None)
    if not p:
        raise HTTPException(404, "No such project")
    turns = report.project_turns(con, p["id"])
    chats = con.execute("SELECT id, name, created_at FROM conversations WHERE project_id = ? AND excluded = 0 "
                        "ORDER BY created_at", (p["id"],)).fetchall()
    return render(request, "project.html", user, p=p, turns=turns, chats=chats, settings=report.settings(con),
                  sync=sync.status(), activity=report.active_times(con, p["id"]), tz=report.tz_label(con))


@app.get("/dive", response_class=HTMLResponse)
def dive_all(request: Request, sort: str = "credits-desc", user=Depends(user_of), con=Depends(get_con)):
    rows = report.projects(con, sort)
    blocks = [(p, report.project_turns(con, p["id"])) for p in rows]
    return render(request, "dive.html", user, blocks=blocks, total=report.totals(rows, con),
                  settings=report.settings(con), sync=sync.status(), sort=sort)


def _csv(rows, header, filename):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/export/summary.csv")
def export_summary(sort: str = "credits-desc", user=Depends(user_of), con=Depends(get_con)):
    rows = report.projects(con, sort)
    t = report.totals(rows, con)
    out = [[r["slug"], r["text_bytes"], r["size_h"], r["words"], r["tokens"], r["credits_i"], f"{r['usd']:.2f}",
            r["created_date"], r["last_date"], r["chats"], r["turns"], int(r["runtime_secs"])] for r in rows]
    out.append(["TOTAL", t["text_bytes"], t["size_h"], t["words"], t["tokens"], t["credits"], f"{t['usd']:.2f}",
                "", "", t["chats"], t["turns"], int(t["runtime_secs"])])
    return _csv(out, ["FilenameNoExt", "FileSizeBytes", "FileSizeHuman", "WordCount", "EstTokens", "TotalCredits",
                      "USDValue", "Created", "LastActivity", "Chats", "Turns", "AgentRuntimeSecs"], "credit-summary.csv")


@app.get("/export/dive.csv")
def export_dive(user=Depends(user_of), con=Depends(get_con)):
    out = []
    for p in report.projects(con, "name"):
        for t in report.project_turns(con, p["id"]):
            out.append([p["slug"], t["text_bytes"], t["user_brief"] or "", t["words"], t["tokens"], t["credits_i"],
                        f"{t['usd']:.2f}", t["date"], t["chat_name"], t["agent_brief"] or "",
                        int(t["runtime_secs"] or 0)])
    return _csv(out, ["Filename", "FileSizeBytes", "TopicSummary", "WordCount", "EstTokens", "Credits", "USD",
                      "Date", "Chat", "AgentSummary", "AgentRuntimeSecs"], "credit-dive.csv")


def _pdf(data: bytes, filename: str):
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/export/summary.pdf")
def export_summary_pdf(sort: str = "credits-desc", user=Depends(user_of), con=Depends(get_con)):
    return _pdf(pdf.summary_pdf(_summary_ctx(con, sort)), "credit-summary.pdf")


@app.get("/export/dive.pdf")
def export_dive_pdf(sort: str = "credits-desc", user=Depends(user_of), con=Depends(get_con)):
    rows = report.projects(con, sort)
    blocks = [(p, report.project_turns(con, p["id"])) for p in rows]
    return _pdf(pdf.dive_pdf(blocks, report.totals(rows, con), report.settings(con)), "credit-dive.pdf")


# ------------------------------------------------------------------ sync
@app.post("/api/sync")
def sync_now(request: Request, csrf: str = Form(""), user=Depends(owner_of)):
    check_csrf(user, csrf or request.headers.get("x-csrf-token"))
    started = sync.start_background("manual")
    return JSONResponse({"started": started, **sync.status()})


@app.get("/api/sync/status")
def sync_status(user=Depends(user_of)):
    return sync.status()


# ------------------------------------------------------------------ admin
@app.get("/admin/projects", response_class=HTMLResponse)
def admin_projects(request: Request, msg: str = "", user=Depends(owner_of), con=Depends(get_con)):
    convs = con.execute("""
        SELECT c.id, c.name, c.created_at, c.excluded, c.project_id,
               (SELECT COALESCE(SUM(credits), 0) FROM turns t WHERE t.conversation_id = c.id) AS credits,
               (SELECT COUNT(*) FROM turns t WHERE t.conversation_id = c.id) AS turns
        FROM conversations c ORDER BY c.excluded, c.created_at DESC""").fetchall()
    projects = []
    for r in con.execute("SELECT * FROM projects ORDER BY name").fetchall():
        d = dict(r)
        d["repo_url"] = (json.loads(d.get("extra") or "{}").get("repo_url") or "").strip()
        projects.append(d)
    return render(request, "admin_projects.html", user, convs=convs, projects=projects, msg=msg)


@app.post("/admin/projects/assign")
def admin_assign(conv_id: str = Form(...), project: str = Form(...), new_name: str = Form(""), csrf: str = Form(""),
                 user=Depends(owner_of), con=Depends(get_con)):
    check_csrf(user, csrf)
    if project == "__exclude__":
        con.execute("UPDATE conversations SET excluded = 1 WHERE id = ?", (conv_id,))
    else:
        if project == "__new__":
            name = new_name.strip() or "new-project"
            slug = sync.slugify(name)
            row = con.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
            pid = row["id"] if row else con.execute("INSERT INTO projects(slug, name) VALUES (?, ?)", (slug, name)).lastrowid
        else:
            pid = int(project)
        con.execute("UPDATE conversations SET project_id = ?, excluded = 0 WHERE id = ?", (pid, conv_id))
    con.execute("DELETE FROM projects WHERE id NOT IN (SELECT project_id FROM conversations WHERE project_id IS NOT NULL)")
    con.commit()
    return RedirectResponse("/admin/projects?msg=Saved", status_code=303)


@app.post("/admin/projects/rename")
def admin_rename(project_id: int = Form(...), name: str = Form(...), notes: str = Form(""), repo_url: str = Form(""),
                 csrf: str = Form(""), user=Depends(owner_of), con=Depends(get_con)):
    check_csrf(user, csrf)
    name = name.strip()
    if name:
        slug = sync.slugify(name)
        clash = con.execute("SELECT id FROM projects WHERE slug = ? AND id != ?", (slug, project_id)).fetchone()
        if clash:  # renaming onto an existing project merges the two
            con.execute("UPDATE conversations SET project_id = ? WHERE project_id = ?", (clash["id"], project_id))
            con.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        else:
            row = con.execute("SELECT extra FROM projects WHERE id = ?", (project_id,)).fetchone()
            extra = json.loads((row["extra"] if row else "") or "{}")
            repo = repo_url.strip()
            if repo:
                extra["repo_url"] = repo
            else:
                extra.pop("repo_url", None)
            con.execute("UPDATE projects SET name = ?, slug = ?, notes = ?, extra = ? WHERE id = ?",
                        (name, slug, notes, json.dumps(extra), project_id))
    con.commit()
    return RedirectResponse("/admin/projects?msg=Saved", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, user=Depends(owner_of), con=Depends(get_con)):
    users = con.execute("SELECT id, username, role, created_at FROM users ORDER BY role, username").fetchall()
    return render(request, "admin_users.html", user, users=users)


@app.post("/admin/users/add", response_class=HTMLResponse)
def admin_user_add(request: Request, username: str = Form(...), csrf: str = Form(""), user=Depends(owner_of),
                   con=Depends(get_con)):
    check_csrf(user, csrf)
    username = username.strip()
    users = lambda: con.execute("SELECT id, username, role, created_at FROM users ORDER BY role, username").fetchall()  # noqa: E731
    if not username or con.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return render(request, "admin_users.html", user, users=users(), error="Pick a new, non-empty username.")
    pw = auth.generate_password()
    con.execute("INSERT INTO users(username, pw_hash, role) VALUES (?, ?, 'viewer')", (username, auth.hash_password(pw)))
    con.commit()
    return render(request, "admin_users.html", user, users=users(), new_user=username, new_pw=pw)


@app.post("/admin/users/delete")
def admin_user_delete(user_id: int = Form(...), csrf: str = Form(""), user=Depends(owner_of), con=Depends(get_con)):
    check_csrf(user, csrf)
    con.execute("DELETE FROM users WHERE id = ? AND role = 'viewer'", (user_id,))
    con.commit()
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/account/password", response_class=HTMLResponse)
def change_password(request: Request, current: str = Form(...), new: str = Form(...), csrf: str = Form(""),
                    user=Depends(user_of), con=Depends(get_con)):
    check_csrf(user, csrf)
    row = con.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not auth.verify_password(current, row["pw_hash"]) or len(new) < 10:
        return render(request, "message.html", user, title="Password not changed",
                      message="Current password was wrong or the new one is shorter than 10 characters.")
    con.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (auth.hash_password(new), user["id"]))
    con.commit()
    return render(request, "message.html", user, title="Password changed", message="Your password was updated.")


@app.get("/account", response_class=HTMLResponse)
def account(request: Request, user=Depends(user_of)):
    return render(request, "account.html", user)


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, msg: str = "", user=Depends(owner_of), con=Depends(get_con)):
    s = {k: db.get_setting(con, k) for k in db.DEFAULT_SETTINGS}
    s["redact_terms"] = "\n".join(db.redact_terms(con))
    return render(request, "admin_settings.html", user, s=s, msg=msg)


@app.post("/admin/settings")
def admin_settings_save(rate_usd_per_10k: float = Form(...), tokens_per_word: float = Form(...),
                        brief_llm: str = Form(...), sync_hour_utc: int = Form(...), redact_terms: str = Form(""),
                        rebrief: str = Form(""), csrf: str = Form(""), user=Depends(owner_of), con=Depends(get_con)):
    check_csrf(user, csrf)
    if rate_usd_per_10k <= 0 or tokens_per_word <= 0 or not 0 <= sync_hour_utc <= 23:
        raise HTTPException(400, "Values must be positive; sync hour 0-23")
    db.set_setting(con, "rate_usd_per_10k", str(rate_usd_per_10k))
    db.record_rate(con, rate_usd_per_10k, "settings")  # track cost-per-10k changes over time
    db.set_setting(con, "tokens_per_word", str(tokens_per_word))
    db.set_setting(con, "brief_llm", brief_llm.strip() or db.DEFAULT_SETTINGS["brief_llm"])
    db.set_setting(con, "sync_hour_utc", str(sync_hour_utc))
    terms = [t.strip() for t in redact_terms.splitlines() if t.strip()]
    db.set_setting(con, "redact_terms", json.dumps(terms))
    if rebrief:
        con.execute("UPDATE turns SET brief_hash = NULL")
    con.commit()
    return RedirectResponse("/admin/settings?msg=Saved" + (" (excerpts will be rewritten on the next sync)" if rebrief else ""),
                            status_code=303)
