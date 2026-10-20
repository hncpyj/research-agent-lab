"""
Bringing your own work into a session.

Someone who already has the papers, or the question, or a finished study wants
to start in the middle. Each stage says what it needs (agents/stages.py); this
is how a person supplies those things without running the stage that normally
produces them.

Two rules run through all of it:
- Nothing is guessed. A row that cannot be read is reported as skipped with the
  reason, never silently dropped or filled in with a placeholder.
- Imported work is marked as imported. A gap report you pasted is not evidence
  that this pipeline checked anything, and the report must not read as if it
  were.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Fields a paper may carry. Everything else in a row is kept out.
PAPER_FIELDS = ("title", "authors", "year", "abstract", "url", "venue", "doi",
                "arxiv_id", "findings", "limitation", "future_work", "method")
REQUIRED = ("title",)


class ImportError_(ValueError):
    """The file could not be read at all."""


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _year(value: Any) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _normalise(row: dict) -> dict:
    """One row in this project's shape, from whatever the file called things."""
    aliases = {
        "title": ("title", "Title", "TI", "primary_title", "paper", "name"),
        "authors": ("authors", "author", "Authors", "AU", "creator"),
        "year": ("year", "Year", "PY", "date", "published", "publication_year"),
        "abstract": ("abstract", "Abstract", "AB", "summary", "description"),
        "url": ("url", "URL", "link", "pdf_url", "UR"),
        "venue": ("venue", "journal", "booktitle", "publisher", "JO", "conference"),
        "doi": ("doi", "DOI"),
        "arxiv_id": ("arxiv_id", "arxivId", "eprint", "id", "ID", "key"),
        "findings": ("findings", "finding", "key_findings", "results"),
        "limitation": ("limitation", "limitations"),
        "future_work": ("future_work", "future work", "futureWork"),
        "method": ("method", "methods", "methodology"),
    }
    out: dict = {}
    row = {k: (", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else v)
           for k, v in row.items()}          # "authors": ["Kim", "Lee"] is one field
    lowered = { (k or "").strip().lower(): v for k, v in row.items() }
    for field, names in aliases.items():
        for name in names:
            if name in row and _clean(row[name]):
                out[field] = _clean(row[name])
                break
            key = name.strip().lower()
            if key in lowered and _clean(lowered[key]):
                out[field] = _clean(lowered[key])
                break
    if "year" in out:
        out["year"] = _year(out["year"])
    return out


def parse_papers(text: str, filename: str = "") -> tuple[list[dict], list[str]]:
    """
    Read a paper list from CSV, JSON or BibTeX. Returns (papers, problems);
    a row that cannot be used appears in problems with its reason.
    """
    text = (text or "").strip()
    if not text:
        raise ImportError_("the file is empty")

    name = (filename or "").lower()
    if text[0] in "[{" or name.endswith(".json"):
        rows = _rows_from_json(text)
    elif "@" in text[:200] and re.search(r"@\w+\s*\{", text):
        rows = _rows_from_bibtex(text)
    else:
        rows = _rows_from_csv(text)

    papers, problems = [], []
    seen: set[str] = set()
    for i, row in enumerate(rows, 1):
        paper = _normalise(row)
        missing = [f for f in REQUIRED if not paper.get(f)]
        if missing:
            problems.append(f"row {i}: no {', '.join(missing)} — skipped")
            continue
        key = paper["title"].lower()
        if key in seen:
            problems.append(f"row {i}: the same title appears twice — skipped")
            continue
        seen.add(key)
        if not paper.get("abstract"):
            problems.append(f"row {i} ({paper['title'][:40]}…): no abstract — kept, but gap analysis "
                            "reads abstracts, so it will have less to work with")
        papers.append(paper)
    if not papers:
        raise ImportError_("no usable rows: " + ("; ".join(problems) or "nothing recognisable in the file"))
    return papers, problems


def _rows_from_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ImportError_(f"not valid JSON: {exc}") from exc
    if isinstance(data, dict):
        for key in ("papers", "results", "data", "items", "records"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ImportError_("JSON must be a list of papers, or an object with a list in it")
    return [row for row in data if isinstance(row, dict)]


def _rows_from_csv(text: str) -> list[dict]:
    sample = text[:4096]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ImportError_("the first line must name the columns (title, authors, year, abstract…)")
    rows = [dict(r) for r in reader]
    if not rows:
        raise ImportError_("the file has a header but no rows")
    return rows


_BIB_ENTRY = re.compile(r"@\w+\s*\{([^,]*),(.*?)\n\}", re.S)
_BIB_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*$", re.M | re.S)


def _rows_from_bibtex(text: str) -> list[dict]:
    rows = []
    for key, body in _BIB_ENTRY.findall(text):
        row = {name.lower(): re.sub(r"[{}]", "", value) for name, value in _BIB_FIELD.findall(body)}
        row["key"] = key.strip()
        if "author" in row:
            row["authors"] = row["author"].replace(" and ", ", ")
        rows.append(row)
    if not rows:
        raise ImportError_("no BibTeX entries found")
    return rows


# --- writing it into a session -------------------------------------------------

def import_papers(db, session_id: str, text: str, filename: str = "") -> dict:
    """Store a paper list the user brought. Returns what was taken and what was not."""
    papers, problems = parse_papers(text, filename)
    stored = 0
    for paper in papers:
        record = {f: paper.get(f, "") for f in PAPER_FIELDS}
        record["source"] = "imported"
        if not record.get("arxiv_id"):
            record["arxiv_id"] = f"imported:{abs(hash(record['title'])) % (10 ** 12)}"
        db.save_paper(session_id, record)
        stored += 1
    session = db.get_session(session_id) or {}
    if (session.get("status") or "started") == "started":
        db.update_session(session_id, status="papers_collected")
    db.save_artifact(session_id, "papers_import",
                     {"count": stored, "problems": problems, "filename": filename}, "passed")
    _record(db, session_id, "papers", f"{stored} papers imported from {filename or 'a pasted list'}")
    return {"imported": stored, "problems": problems}


def import_question(db, session_id: str, question: str) -> dict:
    """Use a research question the user wrote, instead of choosing one from gap analysis."""
    text = (question or "").strip()
    if len(text) < 10:
        raise ImportError_("a research question needs to be a sentence")
    db.update_session(session_id, research_question=text, status="question_selected")
    db.save_artifact(session_id, "question",
                     {"text": text, "source": "written by the user",
                      "compliance_notes": "Written by the user; not checked against the data."},
                     "passed")
    _record(db, session_id, "question", "the research question was written by the user")
    return {"question": text}


def import_gap_report(db, session_id: str, report: str) -> dict:
    """Use a gap report the user brought. It is marked as not checked by this pipeline."""
    text = (report or "").strip()
    if len(text) < 40:
        raise ImportError_("a gap report needs to be more than a line")
    header = ("> Imported: this gap report was written outside this pipeline. "
              "Its claims were not checked against the collected papers.\n\n")
    db.update_session(session_id, gap_report=header + text)
    _record(db, session_id, "gap_report",
            "the gap report was imported and has not been checked against the papers")
    try:
        from agents.gap_analysis import record_gap_context
        record_gap_context(db, session_id)
    except Exception as exc:                      # the mark matters more than the bookkeeping
        logger.warning("Could not record the gap context: %s", exc)
    return {"characters": len(text)}


def _record(db, session_id: str, what: str, message: str) -> None:
    """
    Imported work is written into the degradation log, not because it is a
    failure but because the report's limitations must say which parts of the
    chain this pipeline did not do itself.
    """
    try:
        db.save_degradation(session_id, 0, f"imported_{what}", "info", message)
    except Exception as exc:
        logger.warning("Could not record the import of %s: %s", what, exc)
