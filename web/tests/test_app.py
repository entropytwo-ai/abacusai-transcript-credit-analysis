"""Offline tests: a fake Abacus.AI client feeds the sync; no network or credits used."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import auth, briefs, db, main, report, sync


def bot(idx, credits, *texts, secs=60):
    segs = []
    for t in texts:
        segs += [{"type": "text", "segment": t}, {"type": "collapsible_component", "segment": "{tool call}"}]
    return {"role": "BOT", "message_index": idx, "timestamp": f"2026-10-2{idx % 9}T10:00:00+00:00",
            "compute_points_used": credits, "turn_runtime_secs": secs, "segments": segs}


def user(idx, text):
    return {"role": "USER", "message_index": idx, "timestamp": f"2026-10-2{idx % 9}T09:59:00+00:00", "text": text}


CONVS = {
    "c1": {"deployment_conversation_id": "c1", "name": "1-xtree dev", "created_at": "2026-10-20 10:00:00",
           "last_event_created_at": "e1",
           "history": [user(0, "Build xtree for me, my email is me@example.com"), bot(1, 1543.0, "Done.", "Pushed."),
                       user(2, "Add colors"), bot(3, 481.0, "Added colors.")]},
    "c2": {"deployment_conversation_id": "c2", "name": "2-xtree dev", "created_at": "2026-10-25 10:00:00",
           "last_event_created_at": "e2",
           "history": [user(0, "More features please"), bot(1, 44.44, "Added three features.")]},
    "c3": {"deployment_conversation_id": "c3", "name": "RAID Disk Pricer", "created_at": "2026-10-22 10:00:00",
           "last_event_created_at": "e3",
           "history": [user(0, "Price my RAID"), bot(1, 12500.0, "Here is the price table.")]},
    "c4": {"deployment_conversation_id": "c4", "name": "Send Test Message", "created_at": "2026-10-23 10:00:00",
           "last_event_created_at": "e4", "history": [user(0, "hi"), bot(1, 463.0, "hello")]},
}


class FakeConv(dict):
    def to_dict(self):
        return dict(self)


class FakeClient:
    def __init__(self, convs, llm_ok=True):
        self.convs, self.llm_ok, self.gets, self.llm_calls = convs, llm_ok, 0, 0

    def list_deployment_conversations(self, conversation_type=None, limit=None):
        assert conversation_type == "SUPER_AGENT"
        return [{"deployment_conversation_id": k, "last_event_created_at": v["last_event_created_at"]}
                for k, v in self.convs.items()]

    def get_deployment_conversation(self, deployment_conversation_id):
        self.gets += 1
        return FakeConv(self.convs[deployment_conversation_id])

    def evaluate_prompt(self, prompt, **kw):
        self.llm_calls += 1
        if not self.llm_ok:
            raise RuntimeError("llm down")
        turns = json.loads(prompt)["turns"]
        out = {"briefs": [{"id": t["id"], "user": "Asked for work, contact me@example.com",
                           "agent": "Did the work on 10.0.0.5"} for t in turns]}

        class R:
            content = json.dumps(out)
        return R()


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "credits.db")
    db.init()
    (tmp_path / "projects-seed.json").write_text(json.dumps(
        {"projects": {"raid-pricer": ["c3"]}, "excluded": ["c4"], "redact_terms": ["SecretCo"]}))
    return tmp_path


def test_scrub_removes_pii():
    s = briefs.scrub("mail me@x.org from 192.168.1.20 in /home/alice/x, call (606) 555-1234, "
                     "key ghp_abcdefghijklmnop1234 wallet bc1qu6dkcchurnutgc40y6n53s3zm588z9nnkm2ygq SecretCo",
                     ["secretco"])
    for bad in ("me@x.org", "192.168", "alice", "555-1234", "ghp_", "bc1q", "SecretCo"):
        assert bad not in s
    keep = briefs.scrub("v1.2.0 on 2026-10-29 cost 1,543 credits in abacusai-transcript-credit-analysis")
    assert keep == "v1.2.0 on 2026-10-29 cost 1,543 credits in abacusai-transcript-credit-analysis"


def test_clip_and_base_name():
    assert len(briefs.clip("word " * 100)) <= briefs.MAX_BRIEF
    assert sync.base_name("1-xtree dev") == sync.base_name("2-xtree dev") == "xtree dev"
    assert sync.base_name("Linux Dotfiles (part 2)") == "linux dotfiles"


def test_parse_turns_visible_text_only():
    t = sync.parse_turns(CONVS["c1"]["history"])
    assert [x["credits"] for x in t] == [1543.0, 481.0]
    assert t[0]["agent_text"] == "Done.\n\nPushed."
    assert "tool call" not in t[0]["agent_text"]
    assert t[0]["words"] == len("Build xtree for me, my email is me@example.com".split()) + 2


def test_sync_grouping_exclusion_and_briefs(fresh):
    fc = FakeClient(CONVS)
    res = sync.run_sync("test", client=fc)
    assert res["listed"] == 4 and res["updated"] == 4, res
    con = db.connect()
    rows = {r["slug"]: r for r in report.projects(con)}
    assert set(rows) == {"xtree-dev", "raid-pricer"}           # c4 excluded, c1+c2 merged
    assert rows["xtree-dev"]["chats"] == 2 and rows["xtree-dev"]["credits_i"] == 2068
    assert rows["xtree-dev"]["created_date"] == "2026-10-20"
    t = report.project_turns(con, rows["xtree-dev"]["id"])
    assert all("@" not in x["user_brief"] and "10.0.0.5" not in x["agent_brief"] for x in t)
    # second sync: nothing changed -> no downloads, no LLM calls
    fc2 = FakeClient(CONVS)
    sync.run_sync("test", client=fc2)
    assert fc2.gets == 0 and fc2.llm_calls == 0
    # a new chat in the future joins its project automatically
    convs = dict(CONVS, c5={"deployment_conversation_id": "c5", "name": "3-xtree dev", "created_at": "2026-11-01",
                            "last_event_created_at": "e5", "history": [user(0, "again"), bot(1, 100.0, "ok")]})
    fc3 = FakeClient(convs)
    sync.run_sync("test", client=fc3)
    assert fc3.gets == 1
    rows = {r["slug"]: r for r in report.projects(con)}
    assert rows["xtree-dev"]["chats"] == 3


def test_llm_failure_falls_back(fresh):
    sync.run_sync("test", client=FakeClient(CONVS, llm_ok=False))
    con = db.connect()
    srcs = {r["brief_source"] for r in con.execute("SELECT brief_source FROM turns t JOIN conversations c "
                                                   "ON c.id=t.conversation_id WHERE c.excluded=0")}
    assert srcs == {"fallback"}
    row = con.execute("SELECT user_brief FROM turns WHERE conversation_id='c1' AND message_index=1").fetchone()
    assert "me@example.com" not in row["user_brief"]


def test_statistics_match_scanner_rules(fresh):
    sync.run_sync("test", client=FakeClient(CONVS))
    con = db.connect()
    rows = report.projects(con)
    st = report.statistics(rows, con)
    assert st["credits"]["total"] == 2068 + 12500
    assert st["credits"]["mean"] == (2068 + 12500) / 2
    assert st["credits"]["mode"] == 2068                       # tie -> smallest
    assert report.mode_smallest([3, 1, 3, 1]) == 1
    assert st["tokens"]["total"] == sum(r["tokens"] for r in rows)


def login_client(fresh):
    c = TestClient(main.app)
    con = db.connect()
    token = auth.setup_token()
    r = c.post("/setup", data={"token": token, "username": "owner", "password": "correct-horse-1"},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def page_csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def test_web_flow(fresh, monkeypatch):
    with TestClient(main.app) as anon:
        assert anon.get("/healthz").json()["ok"]
        r = anon.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
        assert anon.get("/setup?token=wrong").text.count("not valid")
    c = login_client(fresh)
    assert "already used" in c.get("/setup?token=" + "x").text or "not valid" in c.get("/setup?token=x").text
    sync.run_sync("test", client=FakeClient(CONVS))
    html = c.get("/").text
    for s in ("TOTAL", "Est. Tokens", "Created", "2026-10-20", "14,568", "do <b>not</b>", "Mode"):
        assert s in html, s
    assert "Send Test Message" not in html
    p = c.get("/project/xtree-dev").text
    assert "PROJECT TOTALS" in p and "You:" in p and "Agent:" in p and "me@example.com" not in p
    assert "raid-pricer" in c.get("/dive").text
    csv_text = c.get("/export/summary.csv").text
    assert csv_text.splitlines()[0].startswith("FilenameNoExt,FileSizeBytes,FileSizeHuman,WordCount,EstTokens,TotalCredits,USDValue,Created")
    assert csv_text.splitlines()[-1].startswith("TOTAL,")
    assert c.get("/export/dive.csv").text.startswith("Filename,FileSizeBytes,TopicSummary,WordCount,EstTokens,Credits,USD")

    # PDF exports (dashboard + dive): real PDF bytes with the right content type
    for path in ("/export/summary.pdf", "/export/dive.pdf"):
        r = c.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF" and len(r.content) > 1000

    # sharing: owner adds a viewer, viewer can read but not administer
    csrf = page_csrf(c.get("/admin/users").text)
    assert c.post("/admin/users/add", data={"username": "friend"}).status_code == 400   # no csrf
    r = c.post("/admin/users/add", data={"username": "friend", "csrf": csrf})
    pw = re.search(r'<code class="pw">([^<]+)</code>', r.text).group(1)
    v = TestClient(main.app)
    assert v.post("/login", data={"username": "friend", "password": "nope"}).text.count("Wrong")
    v.post("/login", data={"username": "friend", "password": pw})
    assert "TOTAL" in v.get("/").text
    assert v.get("/admin/projects").status_code == 403
    assert v.post("/api/sync", data={"csrf": "x"}).status_code == 403

    # project admin: move c3 into xtree via rename-merge, then exclude a chat
    csrf = page_csrf(c.get("/admin/projects").text)
    con = db.connect()
    pid = con.execute("SELECT id FROM projects WHERE slug='raid-pricer'").fetchone()["id"]
    c.post("/admin/projects/rename", data={"project_id": pid, "name": "RAID Pricer", "notes": "n", "csrf": csrf})
    assert con.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()["name"] == "RAID Pricer"
    c.post("/admin/projects/assign", data={"conv_id": "c2", "project": "__exclude__", "csrf": csrf})
    assert "2-xtree dev" not in c.get("/project/xtree-dev").text

    # settings change the valuation
    csrf = page_csrf(c.get("/admin/settings").text)
    c.post("/admin/settings", data={"rate_usd_per_10k": "20", "tokens_per_word": "2", "brief_llm": "X",
                                    "sync_hour_utc": "3", "redact_terms": "a\nb", "csrf": csrf})
    assert "$20.00 per 10,000 credits" in c.get("/").text


def test_google_button_hidden_when_unconfigured(fresh, monkeypatch):
    # No Google env -> feature disabled, no button on the login page.
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_GOOGLE_EMAILS", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    from app import google_oauth
    assert google_oauth.enabled() is False
    login_client(fresh)  # create the owner so /login renders the form, not the setup notice
    with TestClient(main.app) as c:
        assert "Sign in with Google" not in c.get("/login").text


def test_google_start_redirects_to_google(fresh, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "789443647456-test.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-test-secret")
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "entropy.two@gmail.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://entropytwo-ai-project-analysis.abacusai.cloud")
    from app import google_oauth
    assert google_oauth.enabled() is True
    login_client(fresh)  # create the owner so /login renders the form
    with TestClient(main.app) as c:
        # Button present on the login page.
        assert "Sign in with Google" in c.get("/login").text
        # Starting the flow 303-redirects to Google with the exact registered redirect_uri + PKCE/state.
        r = c.get("/auth/google?next=/dive", follow_redirects=False)
        assert r.status_code == 303
        loc = r.headers["location"]
        assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(loc).query)
        assert q["redirect_uri"] == ["https://entropytwo-ai-project-analysis.abacusai.cloud/auth/google/callback"]
        assert q["client_id"] == ["789443647456-test.apps.googleusercontent.com"]
        assert q["scope"] == ["openid email profile"]
        assert q["response_type"] == ["code"]
        assert q["code_challenge_method"] == ["S256"]
        assert q.get("state") and q.get("code_challenge")
        # A signed, httponly OAuth state cookie is set and carries the safe next.
        assert auth.OAUTH_COOKIE in r.cookies
        saved = auth.read_oauth_state(r.cookies[auth.OAUTH_COOKIE])
        assert saved and saved["next"] == "/dive" and saved["state"] == q["state"][0]


def test_google_callback_rejects_unlisted_email(fresh, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    monkeypatch.setenv("ALLOWED_GOOGLE_EMAILS", "entropy.two@gmail.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://entropytwo-ai-project-analysis.abacusai.cloud")
    from app import google_oauth
    monkeypatch.setattr(google_oauth, "exchange_code", lambda *a, **k: {"access_token": "x"})
    monkeypatch.setattr(google_oauth, "fetch_userinfo",
                        lambda *a, **k: {"email": "intruder@example.com", "email_verified": True})
    with TestClient(main.app) as c:
        start = c.get("/auth/google", follow_redirects=False)
        from urllib.parse import urlparse, parse_qs
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        c.cookies.set(auth.OAUTH_COOKIE, start.cookies[auth.OAUTH_COOKIE])
        r = c.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
        assert r.status_code == 200  # rendered login page, not a session redirect
        assert "This Google account is not authorized" in r.text
        assert auth.SESSION_COOKIE not in r.cookies
