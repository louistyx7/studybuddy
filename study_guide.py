#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
study_guide.py - builds a downloadable study guide (one HTML file) from a lecture.

Claude fills in a structured form (it never writes HTML). This file turns that form into a
self-contained page: collapsible sections, search, dark mode, and a Print / PDF button.
"""

import html
import re

from claude_call import call_with_tool
from notes_maker import client, MODEL_CHEAP, MAX_CHARS

# detail level -> (most sections, output-token ceiling). A ceiling is not a cost.
DETAIL_LEVELS = {"Concise": (6, 14000), "Standard": (10, 24000), "Detailed": (16, 40000)}

DEFAULT_ACCENT = "#0F766E"

GUIDE_HINTS = {
    "general": "Organise by topic. Use tables for comparisons.",
    "finance": (
        "Finance course. For every key concept give the formula in plain text and a worked "
        "example using the lecture's numbers. Add a section of kind 'warning' for common mistakes "
        "and traps (sign conventions, units, annual vs semi-annual, and so on)."
    ),
    "physio": (
        "Physiotherapy course. Organise by condition or topic. For each one give: a description; "
        "who gets it; subjective findings as a table (Area, Quality, Aggravating, Easing, 24-hour "
        "pattern, History); tests to confirm the hypothesis as a table with the columns Test, How, "
        "Expected finding; alternative or overlapping hypotheses as a table with the columns "
        "Condition and How to tell apart; then exam pearls. Red-flag conditions get kind 'warning'. "
        "Clinical safety comes first."
    ),
}

# ---------- The form Claude fills in ----------
# Not "strict": the form is too big for strict mode (Claude rejects it as too large).
# Instead clean_guide() below checks everything Claude sends back.
STR = {"type": "string"}
STR_LIST = {"type": "array", "items": STR}


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props)}


LIST_BLOCK = _obj({"title": STR, "items": STR_LIST})
TABLE = _obj({"title": STR, "headers": STR_LIST, "rows": {"type": "array", "items": STR_LIST}})
FORMULA = _obj({"name": STR, "formula": STR, "explanation": STR})
EXAMPLE = _obj({"title": STR, "question": STR, "steps": STR_LIST, "answer": STR})
FLOW = _obj({"title": STR, "steps": STR_LIST})
CHART = _obj({
    "kind": {"type": "string", "enum": ["none", "bar", "line"]},
    "title": STR, "x_label": STR, "y_label": STR,
    "categories": STR_LIST,
    "series": {"type": "array", "items": _obj({"name": STR, "values": {"type": "array", "items": {"type": "number"}}})},
})
SECTION = _obj({
    "title": STR,
    "kind": {"type": "string", "enum": ["core", "warning", "extra"]},
    "kicker": STR,
    "description": STR,
    "lists": {"type": "array", "items": LIST_BLOCK},
    "tables": {"type": "array", "items": TABLE},
    "formulas": {"type": "array", "items": FORMULA},
    "examples": {"type": "array", "items": EXAMPLE},
    "chart": CHART,
    "flow": FLOW,
    "pearls": STR_LIST,
})
GUIDE_TOOL = {
    "name": "save_guide",
    "description": "Save the finished study guide.",
    "input_schema": _obj({
        "title": STR, "subtitle": STR, "overview": STR,
        "quick_reference": {"type": "array", "items": LIST_BLOCK},
        "sections": {"type": "array", "items": SECTION},
        "matrices": {"type": "array", "items": TABLE},
    }),
}

EMPTY_CHART = {"kind": "none", "title": "", "x_label": "", "y_label": "", "categories": [], "series": []}
EMPTY_FLOW = {"title": "", "steps": []}

BASE_RULES = """You build a study guide for a university student from lecture text, by calling the save_guide tool exactly once.

Rules:
- Use ONLY information in the lecture text (except 'extra' sections, if allowed below). Keep numbers, definitions and key wording exactly as in the lecture. Never invent numbers, names or statistics.
- The text came from slides, so pictures are not visible. Do not mention layout, pictures or slide numbers.
- Each section covers one major topic, in lecture order. Write short, scannable phrases, not long paragraphs.
- kind: 'core' = taught in the lecture; 'warning' = risks, red flags, common mistakes or traps; 'extra' = beyond the lecture.
- kicker: a 2-4 word category label for the section.
- description: 2-4 sentences. Put **double asterisks** around a few key terms.
- lists: short bullet lists such as 'Key points' or 'Who gets it' (each item under 25 words).
- quick_reference: 2-4 short lists of the most useful facts to know before an exam.
- matrices: side-by-side comparison tables across topics, only if the lecture supports them.
- Fill in every field of the form. Leave anything unused empty: empty string, empty list, chart kind 'none', flow with no steps."""


def build_instructions(style_hint, opts, max_sections):
    rules = [BASE_RULES, f"- Write at most {max_sections} sections.", "- Course style: " + style_hint]
    rules.append(
        "- Use tables for comparisons, symptoms, tests and findings (at most 6 columns, short cells)."
        if opts["tables"] else "- Do not use tables or matrices: leave them empty.")
    rules.append(
        "- Add a chart ONLY where the lecture gives numbers worth plotting. Use only numbers from the "
        "lecture, or simple arithmetic on them. Otherwise chart kind 'none'."
        if opts["charts"] else "- Never add charts: always chart kind 'none'.")
    rules.append(
        "- Add a flow of 3-8 short steps where the lecture describes a process or sequence."
        if opts["diagrams"] else "- Never add flows: leave flow steps empty.")
    rules.append(
        "- Give key formulas in plain text (for example: V = C/(1+r)^1 + ... + (C+F)/(1+r)^N) and worked "
        "examples that use the lecture's numbers. Show every step and double-check each calculation. "
        "If you are not sure of a calculation, leave that example out."
        if opts["examples"] else "- Leave formulas and worked examples empty.")
    rules.append(
        "- Add 2-4 exam pearls per section: sharp tips, classic confusions, must-know contrasts."
        if opts["pearls"] else "- Leave pearls empty.")
    rules.append(
        "- You may add up to 3 sections of kind 'extra' on closely related standard topics that the "
        "lecture does not cover. Keep them accurate, standard and brief."
        if opts["extras"] else "- Add nothing beyond the lecture and never use kind 'extra'.")
    return "\n".join(rules)


# ---------- Checking what Claude sent back ----------
# Claude's answer is not forced into shape, so every piece is checked here.
# Anything malformed is skipped rather than crashing the page.
def _as_list(x):
    return x if isinstance(x, list) else []


def _strs(x):
    return [str(i) for i in _as_list(x) if i is not None and str(i).strip()]


def _keep(fn, items):
    return [x for x in (fn(i) for i in _as_list(items)) if x]


def _clean_list_block(b):
    if not isinstance(b, dict):
        return None
    items = _strs(b.get("items"))
    return {"title": str(b.get("title") or ""), "items": items} if items else None


def _clean_table(t):
    if not isinstance(t, dict):
        return None
    headers = _strs(t.get("headers"))
    rows = [[str(c) for c in r] for r in _as_list(t.get("rows")) if isinstance(r, list)]
    if not headers or not rows:
        return None
    return {"title": str(t.get("title") or ""), "headers": headers, "rows": rows}


def _clean_formula(f):
    if not isinstance(f, dict) or not str(f.get("formula") or "").strip():
        return None
    return {"name": str(f.get("name") or ""), "formula": str(f["formula"]),
            "explanation": str(f.get("explanation") or "")}


def _clean_example(e):
    if not isinstance(e, dict):
        return None
    steps = _strs(e.get("steps"))
    if not steps:
        return None
    return {"title": str(e.get("title") or ""), "question": str(e.get("question") or ""),
            "steps": steps, "answer": str(e.get("answer") or "")}


def _clean_chart(chart):
    chart = chart if isinstance(chart, dict) else {}
    cats = [str(c) for c in _as_list(chart.get("categories"))]
    series = []
    for s in _as_list(chart.get("series")):
        values = s.get("values") if isinstance(s, dict) else None
        if not isinstance(values, list) or len(values) != len(cats):
            continue
        try:
            numbers = [float(v) for v in values]
        except (TypeError, ValueError):
            continue
        series.append({"name": str(s.get("name", "")), "values": numbers})
    if chart.get("kind") in ("bar", "line") and cats and series:
        return {"kind": chart["kind"], "title": str(chart.get("title", "")),
                "x_label": str(chart.get("x_label", "")), "y_label": str(chart.get("y_label", "")),
                "categories": cats, "series": series}
    return EMPTY_CHART


def _clean_flow(flow):
    flow = flow if isinstance(flow, dict) else {}
    steps = _strs(flow.get("steps"))
    return {"title": str(flow.get("title", "")), "steps": steps} if steps else EMPTY_FLOW


def clean_guide(raw, opts):
    """Tidy the form: drop anything the person switched off or that is malformed."""
    if not isinstance(raw, dict):
        raise ValueError("Claude returned an unusable guide.")
    sections = []
    for s in _as_list(raw.get("sections")):
        if not isinstance(s, dict) or not str(s.get("title", "")).strip():
            continue
        kind = s.get("kind") if s.get("kind") in ("core", "warning", "extra") else "core"
        if kind == "extra" and not opts["extras"]:
            continue
        sections.append({
            "title": str(s["title"]).strip(),
            "kind": kind,
            "kicker": str(s.get("kicker") or ""),
            "description": str(s.get("description") or ""),
            "lists": _keep(_clean_list_block, s.get("lists")),
            "tables": _keep(_clean_table, s.get("tables")) if opts["tables"] else [],
            "formulas": _keep(_clean_formula, s.get("formulas")) if opts["examples"] else [],
            "examples": _keep(_clean_example, s.get("examples")) if opts["examples"] else [],
            "pearls": _strs(s.get("pearls")) if opts["pearls"] else [],
            "chart": _clean_chart(s.get("chart")) if opts["charts"] else EMPTY_CHART,
            "flow": _clean_flow(s.get("flow")) if opts["diagrams"] else EMPTY_FLOW,
        })
    if not sections:
        raise ValueError("Claude returned an empty guide.")
    return {
        "title": str(raw.get("title") or "Study Guide"),
        "subtitle": str(raw.get("subtitle") or ""),
        "overview": str(raw.get("overview") or ""),
        "quick_reference": _keep(_clean_list_block, raw.get("quick_reference")),
        "sections": sections,
        "matrices": _keep(_clean_table, raw.get("matrices")) if opts["tables"] else [],
    }


def generate_guide(lecture_text, filename, style, opts, model=MODEL_CHEAP):
    """Returns (guide, tokens_in, tokens_out). opts has: detail, tables, charts, diagrams,
    examples, pearls, extras."""
    if len(lecture_text) > MAX_CHARS:
        raise ValueError("This file has too much text. Please upload a shorter one.")
    max_sections, max_tokens = DETAIL_LEVELS[opts["detail"]]
    system = build_instructions(GUIDE_HINTS.get(style, GUIDE_HINTS["general"]), opts, max_sections)
    user_text = f"Lecture file: {filename}\n\nHere is the lecture text:\n\n{lecture_text}"

    total_in = total_out = 0
    for attempt in range(2):
        response = call_with_tool(client, model=model, system=system, user_text=user_text,
                                  tool=GUIDE_TOOL, max_tokens=max_tokens, effort="low")
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        if response.stop_reason == "max_tokens":
            raise ValueError("The guide was cut off. Try Concise detail, or switch off some extras.")
        for block in response.content:
            if block.type == "tool_use" and block.name == "save_guide":
                try:
                    return clean_guide(block.input, opts), total_in, total_out
                except ValueError:
                    pass
        print(f"Attempt {attempt + 1}: the guide came back unusable, trying again...")
    raise ValueError("Claude did not return a usable guide. Please try again.")


# ---------- Turning the form into a web page ----------
TAGS = {"core": "From Lecture", "warning": "Warning", "extra": "Beyond Slides · Verify"}
KIND_COLOURS = {"warning": "#B42318", "extra": "#6D3FBF"}
PALETTE = ["#0F766E", "#2563EB", "#EA580C", "#7C3AED", "#DC2626", "#CA8A04"]


def _e(text):
    return html.escape(str(text), quote=True)


def _f(text):
    """Escape, then turn **bold** into bold."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(str(text)))


def _num(v):
    return (f"{v:,.2f}".rstrip("0").rstrip(".")) or "0"


def _list_block(b):
    items = b.get("items", [])
    if not items:
        return ""
    lis = "".join(f"<li>{_f(i)}</li>" for i in items)
    return f'<div class="block"><h4>{_e(b.get("title", ""))}</h4><ul>{lis}</ul></div>'


def _table(t):
    headers = [str(h) for h in t.get("headers", [])]
    rows = t.get("rows", [])
    if not headers or not rows:
        return ""
    n = len(headers)
    head = "".join(f"<th>{_f(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        cells = [str(c) for c in r][:n]
        cells += [""] * (n - len(cells))
        body += "<tr>" + "".join(f"<td>{_f(c)}</td>" for c in cells) + "</tr>"
    title = f"<h4>{_e(t['title'])}</h4>" if t.get("title") else ""
    return (f'<div class="block">{title}<div class="tw"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></div>")


def _formula(f):
    return (f'<div class="block formula"><h4>{_e(f.get("name", ""))}</h4>'
            f'<code>{_e(f.get("formula", ""))}</code><div>{_f(f.get("explanation", ""))}</div></div>')


def _example(e):
    steps = "".join(f"<li>{_f(s)}</li>" for s in e.get("steps", []))
    q = f'<p style="margin:0 0 6px"><b>{_f(e["question"])}</b></p>' if e.get("question") else ""
    ans = f'<p style="margin:8px 0 0"><b>Answer:</b> {_f(e["answer"])}</p>' if e.get("answer") else ""
    return (f'<div class="block"><h4>Worked Example: {_e(e.get("title", ""))}</h4>{q}'
            f"<details><summary>Show working and answer</summary><ol>{steps}</ol>{ans}</details></div>")


def _flow(flow):
    if not flow.get("steps"):
        return ""
    parts = '<span class="arrow">→</span>'.join(f'<span class="step">{_f(s)}</span>' for s in flow["steps"])
    return f'<div class="block"><h4>{_e(flow.get("title") or "Process")}</h4><div class="flow">{parts}</div></div>'


def _chart(chart, colours):
    cats, series = chart["categories"], chart["series"]
    if chart["kind"] == "none" or not cats or not series:
        return ""
    W, H, L, R, T, B = 640, 300, 60, 16, 16, 60
    vals = [v for s in series for v in s["values"]]
    lo, hi = min(vals), max(vals)
    if chart["kind"] == "bar":
        lo, hi = min(lo, 0), max(hi, 0)
    else:
        pad = (hi - lo) * 0.08 or 1
        lo, hi = lo - pad, hi + pad
    if hi == lo:
        hi = lo + 1

    def y(v):
        return T + (H - T - B) * (1 - (v - lo) / (hi - lo))

    n = len(cats)
    step = (W - L - R) / n
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{_e(chart["title"])}">']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        out.append(f'<line x1="{L}" y1="{y(v):.1f}" x2="{W - R}" y2="{y(v):.1f}" class="grid"/>')
        out.append(f'<text x="{L - 6}" y="{y(v) + 4:.1f}" class="ax" text-anchor="end">{_num(v)}</text>')
    if chart["kind"] == "bar":
        k = len(series)
        bw = step * 0.7 / k
        base = y(0)
        for si, s in enumerate(series):
            for i, v in enumerate(s["values"]):
                x = L + step * i + step * 0.15 + bw * si
                top = y(v)
                out.append(f'<rect x="{x:.1f}" y="{min(top, base):.1f}" width="{bw:.1f}" '
                           f'height="{max(abs(base - top), 1):.1f}" fill="{colours[si % len(colours)]}" rx="2"/>')
    else:
        for si, s in enumerate(series):
            col = colours[si % len(colours)]
            pts = [(L + step * (i + 0.5), y(v)) for i, v in enumerate(s["values"])]
            out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.5" '
                       f'points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts)}"/>')
            out += [f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{col}"/>' for px, py in pts]
    skip = 1 if n <= 8 else n // 8 + 1
    for i, c in enumerate(cats):
        if i % skip == 0:
            out.append(f'<text x="{L + step * (i + 0.5):.1f}" y="{H - B + 16}" class="ax" '
                       f'text-anchor="middle">{_e(c[:14])}</text>')
    if chart["x_label"]:
        out.append(f'<text x="{W / 2}" y="{H - 8}" class="ax" text-anchor="middle">{_e(chart["x_label"])}</text>')
    if chart["y_label"]:
        out.append(f'<text transform="rotate(-90 14 {H / 2})" x="14" y="{H / 2}" class="ax" '
                   f'text-anchor="middle">{_e(chart["y_label"])}</text>')
    out.append("</svg>")
    legend = ""
    if len(series) > 1:
        legend = '<div class="legend">' + "".join(
            f'<span><i style="background:{colours[i % len(colours)]}"></i>{_e(s["name"])}</span>'
            for i, s in enumerate(series)) + "</div>"
    return f'<div class="block"><h4>{_e(chart["title"] or "Chart")}</h4>{"".join(out)}{legend}</div>'


def _section_body(s, colours):
    out = []
    if s["description"]:
        out.append(f'<div class="block"><h4>Description</h4><p style="margin:0">{_f(s["description"])}</p></div>')
    out += [_list_block(b) for b in s["lists"]]
    out += [_formula(f) for f in s["formulas"]]
    out += [_table(t) for t in s["tables"]]
    out.append(_flow(s["flow"]))
    out.append(_chart(s["chart"], colours))
    out += [_example(e) for e in s["examples"]]
    if s["pearls"]:
        lis = "".join(f"<li>{_f(p)}</li>" for p in s["pearls"])
        out.append(f'<div class="pearls"><h4>Exam Pearls</h4><ul>{lis}</ul></div>')
    return "".join(out)


CSS = """
:root{--accent:#0F766E;--bg:#EEF2F1;--card:#FFFFFF;--panel:#F3F6FA;--text:#1F2937;--muted:#5B6776;--line:#DDE3EA;--head:#17325C;--pearl-bg:#FFF6D6;--pearl-line:#F0DC93;--pearl-text:#6B4E00;--thead:#E8EEF5}
[data-theme=dark]{--bg:#0F1716;--card:#16211F;--panel:#1B2826;--text:#E5E7EB;--muted:#9AA8B2;--line:#2A3835;--head:#A9C7F5;--pearl-bg:#2B2512;--pearl-line:#5A4A12;--pearl-text:#F2D98A;--thead:#1E2D2B}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
header.top{background:var(--accent);color:#fff;padding:26px 24px 20px}
header.top h1{margin:0 0 4px;font-size:26px}
header.top p{margin:4px 0 0;opacity:.92;max-width:900px}
header.top .meta{font-size:12.5px;opacity:.8}
.tools{position:sticky;top:0;z-index:5;display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:10px 24px;background:var(--card);border-bottom:1px solid var(--line)}
.tools input{flex:1;min-width:160px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);font:inherit}
.tools button{padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);cursor:pointer;font:inherit}
.tools button:hover{border-color:var(--accent)}
.layout{display:grid;grid-template-columns:230px 1fr;gap:20px;max-width:1180px;margin:0 auto;padding:20px 24px 40px}
nav.toc{position:sticky;top:64px;align-self:start;max-height:calc(100vh - 84px);overflow:auto;font-size:13px}
nav.toc a{display:flex;gap:8px;padding:6px 8px;border-radius:6px;color:var(--text);text-decoration:none}
nav.toc a:hover{background:var(--panel)}
nav.toc b{color:var(--muted);min-width:22px}
@media (max-width:820px){.layout{grid-template-columns:1fr}nav.toc{display:none}}
details.card{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:16px;overflow:hidden}
details.card>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;padding:12px 16px;color:#fff;background:var(--c)}
details.card>summary::-webkit-details-marker{display:none}
.num{font-size:26px;font-weight:700;opacity:.55}
.ttl{flex:1}
.ttl small{display:block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.88}
.ttl strong{font-size:18px}
.pill{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;background:rgba(255,255,255,.22);padding:3px 9px;border-radius:99px;white-space:nowrap}
.body{padding:14px 16px 18px;display:grid;gap:14px}
.block{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.block h4,.pearls h4{margin:0 0 8px;font-size:11.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--head)}
.block ul,.block ol{margin:0;padding-left:20px}
.block li{margin:3px 0}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th{background:var(--thead);color:var(--head);text-align:left;padding:7px 10px;font-size:12.5px}
td{padding:7px 10px;border-top:1px solid var(--line);vertical-align:top}
td:first-child{font-weight:600;color:var(--head)}
.formula code{display:block;margin:6px 0;padding:8px 10px;background:var(--card);border:1px solid var(--line);border-radius:8px;font:13.5px/1.5 ui-monospace,Menlo,Consolas,monospace;overflow-x:auto;white-space:pre-wrap}
.block details summary{cursor:pointer;color:var(--accent);font-weight:600}
.pearls{background:var(--pearl-bg);border:1px solid var(--pearl-line);color:var(--pearl-text);border-radius:10px;padding:12px 14px}
.pearls h4{color:var(--pearl-text)}
.pearls ul{margin:0;padding-left:20px}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.flow .step{background:var(--card);border:1.5px solid var(--accent);border-radius:8px;padding:6px 10px;font-size:13.5px}
.flow .arrow{color:var(--muted)}
.chart{width:100%;height:auto}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .ax{fill:var(--muted);font-size:11px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-top:6px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.hidden{display:none!important}
footer{text-align:center;color:var(--muted);font-size:12px;padding:0 16px 30px}
@media print{
:root,:root[data-theme=dark]{--bg:#fff;--card:#fff;--panel:#fff;--text:#000;--muted:#444;--line:#ccc;--head:#17325C;--thead:#EEE;--pearl-bg:#FFF6D6;--pearl-text:#6B4E00}
.tools,nav.toc{display:none}
.layout{display:block;padding:0}
header.top,details.card>summary{-webkit-print-color-adjust:exact;print-color-adjust:exact}
details.card{break-inside:auto}
.block,.pearls{break-inside:avoid}
}
"""

HEAD_JS = ("(function(){var t=null;try{t=localStorage.getItem('sg-theme')}catch(e){}"
           "document.documentElement.setAttribute('data-theme',t||'__THEME__');})();")

JS = """
(function(){
var d=document,root=d.documentElement;
function cards(){return Array.prototype.slice.call(d.querySelectorAll('details.card'));}
function setAll(o){cards().forEach(function(c){c.open=o;});}
d.getElementById('expand').onclick=function(){setAll(true)};
d.getElementById('collapse').onclick=function(){setAll(false)};
d.getElementById('theme').onclick=function(){
  var t=root.getAttribute('data-theme')==='dark'?'light':'dark';
  root.setAttribute('data-theme',t);try{localStorage.setItem('sg-theme',t)}catch(e){}
};
function openEverything(){d.querySelectorAll('details').forEach(function(x){x.open=true;});}
d.getElementById('print').onclick=function(){openEverything();window.print();};
window.addEventListener('beforeprint',openEverything);
d.getElementById('q').addEventListener('input',function(){
  var q=this.value.trim().toLowerCase();
  cards().forEach(function(c){
    var show=!q||c.textContent.toLowerCase().indexOf(q)!==-1;
    c.classList.toggle('hidden',!show);
    if(q&&show)c.open=true;
    var l=d.querySelector('nav.toc a[href="#'+c.id+'"]');if(l)l.classList.toggle('hidden',!show);
  });
});
d.querySelectorAll('nav.toc a').forEach(function(a){a.addEventListener('click',function(){
  var t=d.getElementById(a.getAttribute('href').slice(1));if(t)t.open=true;});});
})();
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="__THEME__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
<script>__HEADJS__</script>
</head>
<body>
<header class="top"><h1>__TITLE__</h1><p>__SUBTITLE__</p><p>__OVERVIEW__</p><p class="meta">__COUNT__</p></header>
<div class="tools"><input id="q" type="search" placeholder="Search this guide..."><button id="expand">Expand All</button><button id="collapse">Collapse All</button><button id="theme">Dark / Light</button><button id="print">Print / PDF</button></div>
<div class="layout"><nav class="toc">__TOC__</nav><main>__CARDS__</main></div>
<footer>Made with StudyBuddy. This is an AI-made study aid: check facts and numbers against your original slides.</footer>
<script>__JS__</script>
</body>
</html>"""


def _fill(template, values):
    """Fill the __NAME__ gaps in one pass, so the text we insert is never searched again."""
    return re.sub(r"__([A-Z]+)__", lambda m: values.get(m.group(1), m.group(0)), template)


def render_html(guide, accent=DEFAULT_ACCENT, default_theme="dark"):
    """Turn a saved guide into one self-contained HTML page (a string)."""
    accent = accent if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(accent)) else DEFAULT_ACCENT
    theme = "light" if default_theme == "light" else "dark"
    colours = [accent] + PALETTE[1:]
    cards, toc = [], []

    def add(cid, num, title, kicker, pill, colour, body):
        toc.append(f'<a href="#{cid}"><b>{num}</b><span>{_e(title)}</span></a>')
        cards.append(
            f'<details class="card" id="{cid}" style="--c:{colour}" open>'
            f'<summary><span class="num">{num}</span><span class="ttl"><small>{_e(kicker)}</small>'
            f"<strong>{_e(title)}</strong></span><span class=\"pill\">{_e(pill)}</span></summary>"
            f'<div class="body">{body}</div></details>')

    if guide["quick_reference"]:
        add("quick", "★", "Quick Reference", "Start here", "Toolkit", accent,
            "".join(_list_block(b) for b in guide["quick_reference"]))
    for i, s in enumerate(guide["sections"], start=1):
        colour = KIND_COLOURS.get(s["kind"], accent)
        add(f"s{i}", f"{i:02d}", s["title"], s["kicker"] or "Topic", TAGS[s["kind"]], colour,
            _section_body(s, colours))
    if guide["matrices"]:
        add("matrices", "⇄", "Comparison Tables", "Side by side", "Compare", accent,
            "".join(_table(t) for t in guide["matrices"]))

    values = {
        "THEME": theme,
        "TITLE": _e(guide["title"]),
        "SUBTITLE": _f(guide["subtitle"]),
        "OVERVIEW": _f(guide["overview"]),
        "COUNT": f"{len(guide['sections'])} sections",
        "CSS": CSS + f":root{{--accent:{accent}}}",
        "HEADJS": HEAD_JS.replace("__THEME__", theme),
        "TOC": "".join(toc),
        "CARDS": "".join(cards),
        "JS": JS,
    }
    return _fill(TEMPLATE, values)