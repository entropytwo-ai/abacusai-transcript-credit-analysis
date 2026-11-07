"""PDF exports for the dashboard (summary) and the dive-in view.

Built with fpdf2 (pure Python, no system libraries) so a fresh install keeps working.
Text is sanitised to latin-1 because the built-in fonts are not Unicode; the excerpts
are AI-written English summaries, so this only swaps a few typographic characters.
"""
from datetime import datetime, timezone

from fpdf import FPDF

# Swap the common non-latin-1 characters that show up in excerpts for ASCII look-alikes.
_SUBS = {
    "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"',
    "\u201d": '"', "\u2026": "...", "\u2022": "*", "\u00a0": " ", "\u2192": "->",
    "\u2191": "^", "\u25b2": "^", "\u25bc": "v", "\u20ac": "EUR", "\u00b7": "-",
}


def _s(v) -> str:
    """Make any value safe for the built-in latin-1 PDF fonts."""
    t = "" if v is None else str(v)
    for a, b in _SUBS.items():
        t = t.replace(a, b)
    return t.encode("latin-1", "replace").decode("latin-1")


def _n0(v) -> str:
    return f"{int(round(v or 0)):,}"


def _n2(v) -> str:
    return f"{(v or 0):,.2f}"


def _money(v) -> str:
    return f"${(v or 0):,.2f}"


def _mins(secs) -> str:
    s = secs or 0
    if s <= 0:
        return ""
    return "<1 min" if s < 60 else f"{s / 60:,.0f} min"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class _PDF(FPDF):
    title_text = ""

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(130)
        self.cell(0, 8, _s(f"Generated {_stamp()}"), align="L")
        self.cell(0, 8, _s(f"Page {self.page_no()}/{{nb}}"), align="R")
        self.set_text_color(0)


def _heading(pdf, title, subtitle=""):
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _s(title), new_x="LMARGIN", new_y="NEXT")
    if subtitle:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(90)
        pdf.multi_cell(0, 5, _s(subtitle), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
    pdf.ln(2)


def summary_pdf(ctx: dict) -> bytes:
    """Dashboard: totals first, then one row per project, then the statistics table."""
    rows = ctx["rows"]
    t = ctx["total"]
    st = ctx["stats"]
    s = ctx["settings"]
    pdf = _PDF(orientation="L", format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(12, 12, 12)
    pdf.alias_nb_pages()
    pdf.add_page()
    _heading(pdf, "Credit usage by project",
             f"Total {_n0(t['credits'])} credits - {_money(t['usd'])} - "
             f"{t['files']} projects / {t['chats']} chats / {t['turns']} turns")

    headers = ["Project", "Created", "Last activity", "Chats", "Turns", "Text Size",
               "Words", "Est. Tokens", "Total Credits", "USD Value"]
    widths = (62, 24, 26, 16, 16, 22, 28, 28, 30, 28)
    nums = {3, 4, 5, 6, 7, 8, 9}

    pdf.set_font("Helvetica", "", 8)
    with pdf.table(col_widths=widths, text_align=["LEFT" if i not in nums else "RIGHT" for i in range(len(headers))],
                   line_height=5.2, first_row_as_headings=True, headings_style=_HEAD) as table:
        table.row([_s(h) for h in headers])
        # Totals at the top of the data.
        total_cells = ["TOTAL", "", "", _n0(t["chats"]), _n0(t["turns"]), _s(t["size_h"]),
                       _n0(t["words"]), _n0(t["tokens"]), _n0(t["credits"]), _money(t["usd"])]
        tr = table.row()
        for c in total_cells:
            tr.cell(_s(c), style=_TOTAL_STYLE)
        for r in rows:
            table.row([_s(r["name"]), _s(r["created_date"]), _s(r["last_date"]), _n0(r["chats"]),
                       _n0(r["turns"]), _s(r["size_h"]), _n0(r["words"]), _n0(r["tokens"]),
                       _n0(r["credits_i"]), _money(r["usd"])])

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Statistical summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 4.5, _s(f"Valuation: ${s['rate']:.2f} per 10,000 credits - "
                              f"Est. Tokens = words x {s['tpw']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(1)

    sheaders = ["Metric", "Credits", "USD Value", "Words", "Est. Tokens"]
    swidths = (60, 40, 40, 40, 40)
    srows = [
        [f"Total ({st['n']} project{'' if st['n'] == 1 else 's'})", _n0(st["credits"]["total"]),
         _money(st["usd"]["total"]), _n0(st["words"]["total"]), _n0(st["tokens"]["total"])],
        ["Mean", _n2(st["credits"]["mean"]), _money(st["usd"]["mean"]), _n2(st["words"]["mean"]), _n2(st["tokens"]["mean"])],
        ["Median", _n2(st["credits"]["median"]), _money(st["usd"]["median"]), _n2(st["words"]["median"]), _n2(st["tokens"]["median"])],
        ["Mode", _n0(st["credits"]["mode"]), _money(st["usd"]["mode"]), _n0(st["words"]["mode"]), _n0(st["tokens"]["mode"])],
    ]
    with pdf.table(col_widths=swidths, text_align=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"],
                   line_height=5.5, first_row_as_headings=True, headings_style=_HEAD) as table:
        table.row([_s(h) for h in sheaders])
        for row in srows:
            table.row([_s(c) for c in row])

    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 4, _s("Note: Words and Est. Tokens cover only the chat transcript text (your prompts and the "
                            "agent's visible replies). They do not include the background agent work (programming, tool "
                            "calls, testing) that the credits actually paid for, so they understate the real tokens used."),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    return bytes(pdf.output())


def dive_pdf(blocks: list, total: dict, settings: dict) -> bytes:
    """Dive-in: every project with its turns (date, excerpt, words, tokens, credits, USD)."""
    pdf = _PDF(orientation="L", format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(12, 12, 12)
    pdf.alias_nb_pages()
    pdf.add_page()
    _heading(pdf, "Dive-in: all projects",
             f"{total['files']} projects - {_n0(total['credits'])} credits - {_money(total['usd'])}")

    headers = ["Date", "Context (You / Agent)", "Words", "Est. Tokens", "Run time", "Credits", "USD"]
    widths = (24, 149, 20, 24, 22, 22, 22)
    aligns = ["LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"]

    for p, turns in blocks:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, _s(f"{p['name']}  ({p['size_h']}, created {p['created_date']})"),
                       new_x="LMARGIN", new_y="NEXT")
        show_chat = p["chats"] > 1
        pdf.set_font("Helvetica", "", 7.5)
        with pdf.table(col_widths=widths, text_align=aligns, line_height=4.6,
                       first_row_as_headings=True, headings_style=_HEAD) as table:
            table.row([_s(h) for h in headers])
            for tr in turns:
                date = tr["date"] + (f"\n{tr['chat_name']}" if show_chat else "")
                att = ""
                if tr.get("attachments"):
                    att = "[" + ", ".join(tr["attachments"]) + "] "
                ctx = (f"You: {att}{tr.get('user_brief') or '(excerpt pending next sync)'}\n"
                       f"Agent: {tr.get('agent_brief') or '(excerpt pending next sync)'}")
                table.row([_s(date), _s(ctx), _n0(tr["words"]), _n0(tr["tokens"]),
                           _s(_mins(tr.get("runtime_secs"))), _n0(tr["credits_i"]), _money(tr["usd"])])
            # Project totals row.
            total_row = table.row()
            total_row.cell(_s(f"PROJECT TOTALS ({p['turns']} turns)"), colspan=2, style=_TOTAL_STYLE)
            for c in (_n0(p["words"]), _n0(p["tokens"]), _s(_mins(p["runtime_secs"])),
                      _n0(p["credits_i"]), _money(p["usd"])):
                total_row.cell(_s(c), style=_TOTAL_STYLE)

    return bytes(pdf.output())


# Styles are created after FPDF import so FontFace is available.
from fpdf.fonts import FontFace  # noqa: E402

_HEAD = FontFace(emphasis="BOLD", color=(220, 240, 220), fill_color=(15, 26, 15))
_TOTAL_STYLE = FontFace(emphasis="BOLD", fill_color=(235, 240, 235))
