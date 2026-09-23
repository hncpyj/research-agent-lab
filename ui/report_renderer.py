"""
ReportRenderer

Converts a structured JSON report (produced by ReportAgent) into:
  - Markdown (.md)       — instant, no deps
  - LaTeX   (.tex)       — instant, no deps (uses built-in template)
  - PDF     (.pdf)       — requires weasyprint; falls back gracefully

All renders are deterministic string operations on the same JSON — the LLM
is called exactly once (in ReportAgent.generate).
"""

from __future__ import annotations

import logging
import re
import textwrap
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section order for all formats
# ---------------------------------------------------------------------------

SECTION_KEYS = [
    ("abstract",     "Abstract"),
    ("introduction", "Introduction"),
    ("related_work", "Related Work"),
    ("methodology",  "Methodology"),
    ("results",      "Results"),
    ("discussion",   "Discussion"),
    ("limitations",  "Limitations"),
    ("review",       "Review notes"),
    ("conclusion",   "Conclusion"),
]


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def to_markdown(report: dict) -> str:
    title = report.get("title", "Research Report")
    today = date.today().isoformat()

    lines = [
        f"# {title}",
        "",
        f"*Generated: {today}*",
        "",
        "---",
        "",
    ]

    for key, heading in SECTION_KEYS:
        content = report.get(key, "").strip()
        if content:
            lines += [f"## {heading}", "", content, ""]

    refs = report.get("references", [])
    if refs:
        lines += ["## References", ""]
        # The stored key is the number the report's text cites. Renumbering the
        # list here pointed every citation at a different paper (2026-09-20:
        # the text cited [11]; that paper was printed as [4]).
        for i, r in enumerate(refs, 1):
            authors = r.get("authors", "")
            title_r = r.get("title", "")
            venue   = r.get("venue", "")
            year    = r.get("year", "")
            key     = r.get("key") or f"[{i}]"
            lines.append(f"{key} {authors}. *{title_r}*. {venue}, {year}.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LaTeX renderer
# ---------------------------------------------------------------------------

_LATEX_PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=2.5cm]{geometry}
\usepackage{hyperref}
\usepackage{booktabs}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{parskip}
\usepackage{microtype}
\hypersetup{colorlinks=true, linkcolor=blue, citecolor=blue, urlcolor=blue}
"""

def _latex_escape(text: str) -> str:
    """Escape special LaTeX characters in plain text."""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&",  r"\&"),
        ("%",  r"\%"),
        ("$",  r"\$"),
        ("#",  r"\#"),
        ("_",  r"\_"),
        ("{",  r"\{"),
        ("}",  r"\}"),
        ("~",  r"\textasciitilde{}"),
        ("^",  r"\textasciicircum{}"),
    ]
    for char, repl in replacements:
        text = text.replace(char, repl)
    # Convert markdown bold **text** → \textbf{text}
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    # Convert markdown italic *text* → \textit{text}
    text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)
    return text


def to_latex(report: dict) -> str:
    title   = _latex_escape(report.get("title", "Research Report"))
    today   = date.today().isoformat()

    body_parts = [
        _LATEX_PREAMBLE,
        "",
        r"\begin{document}",
        "",
        r"\title{" + title + "}",
        r"\author{AI Research Agent}",
        r"\date{" + today + "}",
        r"\maketitle",
        r"\tableofcontents",
        r"\newpage",
        "",
    ]

    for key, heading in SECTION_KEYS:
        content = report.get(key, "").strip()
        if not content:
            continue
        body_parts.append(r"\section{" + heading + "}")
        body_parts.append("")
        # Split into paragraphs
        for para in content.split("\n\n"):
            para = para.strip()
            if para:
                body_parts.append(_latex_escape(para))
                body_parts.append("")

    refs = report.get("references", [])
    if refs:
        body_parts += [r"\section{References}", r"\begin{description}"]
        for i, r in enumerate(refs, 1):
            authors = _latex_escape(r.get("authors", ""))
            title_r = _latex_escape(r.get("title", ""))
            venue   = _latex_escape(r.get("venue", ""))
            year    = r.get("year", "")
            key     = _latex_escape(r.get("key") or f"[{i}]")
            body_parts.append(
                r"\item[" + key + "] " + authors +
                r". \textit{" + title_r + r"}. " +
                venue + ", " + year + "."
            )
        body_parts += [r"\end{description}", ""]

    body_parts.append(r"\end{document}")
    return "\n".join(body_parts)


# ---------------------------------------------------------------------------
# PDF renderer  (weasyprint → HTML→PDF; falls back to HTML-only bytes)
# ---------------------------------------------------------------------------

_HTML_CSS = """\
body {
    font-family: 'Times New Roman', Times, serif;
    font-size: 12pt;
    line-height: 1.6;
    max-width: 800px;
    margin: 40px auto;
    padding: 0 20px;
    color: #111;
}
h1 { font-size: 22pt; text-align: center; margin-bottom: 4px; }
h2 { font-size: 14pt; margin-top: 28px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
.meta { text-align: center; color: #555; font-size: 10pt; margin-bottom: 24px; }
p { margin: 10px 0; text-align: justify; }
ol { margin: 8px 0 8px 20px; }
ol li { margin-bottom: 6px; font-size: 10pt; }
@media print {
    body { margin: 0; }
    h2 { page-break-after: avoid; }
}
"""

def _report_to_html(report: dict) -> str:
    import html as _html

    def esc(t): return _html.escape(str(t))
    def paras(text):
        return "".join(
            f"<p>{esc(p.strip())}</p>"
            for p in text.split("\n\n") if p.strip()
        )

    title = esc(report.get("title", "Research Report"))
    today = date.today().isoformat()

    sections_html = ""
    for key, heading in SECTION_KEYS:
        content = report.get(key, "").strip()
        if content:
            sections_html += f"<h2>{esc(heading)}</h2>\n{paras(content)}\n"

    refs = report.get("references", [])
    refs_html = ""
    if refs:
        items = ""
        for i, r in enumerate(refs, 1):
            a = esc(r.get("authors", ""))
            t = esc(r.get("title", ""))
            v = esc(r.get("venue", ""))
            y = esc(r.get("year", ""))
            k = esc(r.get("key") or f"[{i}]")
            items += f"<li>{k} {a}. <em>{t}</em>. {v}, {y}.</li>\n"
        refs_html = f'<h2>References</h2>\n<ul style="list-style:none;padding-left:0">\n{items}</ul>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>{title}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">Generated: {today}</div>
{sections_html}
{refs_html}
</body>
</html>"""


def to_pdf_bytes(report: dict) -> tuple[bytes, str, str]:
    """
    Returns (bytes, mimetype, why_not_pdf).

    Tries weasyprint first and falls back to HTML with print CSS. The reason
    is returned rather than swallowed: until 2026-09-20 the fallback was
    silent and the browser still saved the file as report.pdf, which then
    would not open.
    """
    html_str = _report_to_html(report)

    try:
        from weasyprint import HTML as WP_HTML
        return WP_HTML(string=html_str).write_pdf(), "application/pdf", ""
    except ImportError:
        why = ("weasyprint is not installed, so this is HTML, not PDF: "
               "open it and print to PDF, or run python -m pip install weasyprint")
    except Exception as exc:
        why = f"PDF rendering failed ({type(exc).__name__}: {exc}); this is HTML instead"
        logger.warning("PDF rendering failed: %s", exc)

    return html_str.encode("utf-8"), "text/html; charset=utf-8", why


def to_html(report: dict) -> str:
    """Return the HTML string for in-browser preview."""
    return _report_to_html(report)


# ---------------------------------------------------------------------------
# Save all formats to disk
# ---------------------------------------------------------------------------

def save_all(report: dict, out_dir: Path) -> dict[str, Path]:
    """
    Write .md, .tex, and .html to out_dir.
    Returns {format: Path} dict.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\-]", "_", report.get("title", "report"))[:60]

    paths = {}
    paths["md"]   = out_dir / f"{slug}.md"
    paths["tex"]  = out_dir / f"{slug}.tex"
    paths["html"] = out_dir / f"{slug}.html"

    paths["md"].write_text(to_markdown(report), encoding="utf-8")
    paths["tex"].write_text(to_latex(report),   encoding="utf-8")
    paths["html"].write_text(to_html(report),   encoding="utf-8")

    return paths
