"""Short, PII-free context excerpts ("briefs") for each turn.

Pipeline: scrub the raw text -> ask an LLM for a <=2-line brief of what the user
asked and what the agent did -> scrub the LLM output again. If the LLM is not
available, a scrubbed extract of the first sentence is used instead.
"""
import json
import logging
import re

log = logging.getLogger("briefs")

MAX_BRIEF = 200          # characters; the UI clamps to two lines as well

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", re.S), "[key]"),
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[email]"),
    (re.compile(r"https?://\S+"), "[link]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat|sk|pk|xox[abpr])[-_][A-Za-z0-9_\-]{10,}"), "[secret]"),
    (re.compile(r"\b(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}\b"), "[wallet]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?::\d+)?\b"), "[ip]"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b"), "[ip]"),
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), "[mac]"),
    (re.compile(r"(?:/home|/Users|/root)/[^/\s]+"), "~"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+"), "~"),
    (re.compile(r"\b[\w.-]+@[\w.-]+:"), "[host]:"),                 # user@host: prompts
    (re.compile(r"(?<![\w.-])(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w.-])"), "[phone]"),
    (re.compile(r"\b(?=[A-Za-z0-9+/_]*\d)(?=[A-Za-z0-9+/_]*[A-Za-z])[A-Za-z0-9+/_]{32,}={0,2}"), "[secret]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|token|api[_ -]?key|secret)\b\s*[:=]\s*\S+"), r"\1: [hidden]"),
]


def scrub(text: str, terms=()) -> str:
    """Remove personal or secret data. `terms` are extra words (names, usernames, hostnames)."""
    if not text:
        return ""
    for rx, rep in _PATTERNS:
        text = rx.sub(rep, text)
    for t in sorted({t.strip() for t in terms if t and t.strip()}, key=len, reverse=True):
        text = re.sub(r"(?i)(?<![\w-])" + re.escape(t) + r"(?![\w-])", "[redacted]", text)
    return text


def clip(text: str, n: int = MAX_BRIEF) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    cut = text[: n - 1]
    cut = cut[: cut.rfind(" ")] if " " in cut[n // 2:] else cut
    return cut.rstrip(" ,;:-") + "…"


def _plain(text: str) -> str:
    """Strip markdown/code so fallback excerpts read as prose."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[#>*_|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fallback(user_text: str, agent_text: str, terms=()) -> tuple:
    def first(t):
        t = _plain(scrub(t, terms))
        m = re.match(r"(.{20,}?[.!?])(\s|$)", t)
        return clip(m.group(1) if m else t)
    return first(user_text) or "(no prompt text)", first(agent_text) or "(no visible reply)"


SYSTEM = (
    "You write very short context notes for a credit-usage report of AI agent chat sessions. "
    "For each turn, write 'user': what the user asked or said, and 'agent': what the agent said or did in reply. "
    "Each note is ONE plain sentence, at most 160 characters, no markdown, no quotes from code. "
    "The notes are shown after the labels 'You:' and 'Agent:', so start with a past-tense verb "
    "(e.g. 'Asked for…', 'Reported…', 'Built…') and never start with 'The user' or 'The agent'. "
    "Never include personal or confidential data: no names of people, usernames, account or org names, "
    "email addresses, phone numbers, hostnames, IP or MAC addresses, URLs, file paths with user folders, "
    "passwords, keys, tokens, wallet addresses or street addresses. Refer to them generically "
    "(e.g. 'the user's GitHub repo', 'a kiosk host'). Project and tool names (e.g. NixOS, Proxmox, xtree) are fine. "
    "Return JSON: {\"briefs\": [{\"id\": <id>, \"user\": \"...\", \"agent\": \"...\"}, ...]} with one entry per input id."
)


def llm_briefs(client, model: str, items: list, terms=()) -> dict:
    """items: [{'id', 'user_text', 'agent_text'}]. Returns {id: (user_brief, agent_brief)}."""
    payload = [{"id": it["id"],
                "user": scrub(it["user_text"], terms)[:2500],
                "agent": _plain(scrub(it["agent_text"], terms))[:3500]} for it in items]
    resp = client.evaluate_prompt(prompt=json.dumps({"turns": payload}, ensure_ascii=False),
                                  system_message=SYSTEM, llm_name=model, response_type="json",
                                  temperature=0.0, max_tokens=4000)
    content = resp.content.strip()
    content = re.sub(r"^```(?:json)?|```$", "", content).strip()
    data = json.loads(content)
    out = {}
    for b in data.get("briefs", []):
        if not isinstance(b, dict) or "id" not in b:
            continue
        u = clip(scrub(str(b.get("user", "")), terms))
        a = clip(scrub(str(b.get("agent", "")), terms))
        if u or a:
            out[str(b["id"])] = (u or "(no prompt text)", a or "(no visible reply)")
    return out
