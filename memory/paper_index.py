"""
One record per paper, however many sessions have read it.

Papers are stored per session, which is right -- what a session read is part of
what it did -- but it means the same paper exists as many separate rows, and
two questions could not be answered at all: how many distinct papers does this
project rest on, and which of them does it keep coming back to?

So each paper row is also filed under a canonical record. The key is the
strongest identifier the paper has: a DOI, else an arXiv id without its version
suffix, else the title reduced to letters and digits. Nothing is merged that
does not share one of those; guessing that two similar titles are the same
paper would quietly join two bodies of work.

The index repairs itself. Papers saved before this existed, or by a path that
does not call it, are filed the first time something asks about their session.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

import config

logger = logging.getLogger(__name__)

DOI, ARXIV, TITLE = "doi", "arxiv", "title"

_DOI_PREFIX = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.I)
_ARXIV_VERSION = re.compile(r"v\d+$", re.I)
_ARXIV_PREFIX = re.compile(r"^(https?://arxiv\.org/(abs|pdf)/|arxiv:)", re.I)
_NOT_WORD = re.compile(r"[^a-z0-9]+")


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS canonical_papers (
            canonical_id TEXT PRIMARY KEY,
            key_kind     TEXT NOT NULL,
            key_value    TEXT NOT NULL,
            title        TEXT NOT NULL DEFAULT '',
            authors      TEXT NOT NULL DEFAULT '',
            year         INTEGER,
            url          TEXT NOT NULL DEFAULT '',
            doi          TEXT NOT NULL DEFAULT '',
            arxiv_id     TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS paper_occurrences (
            paper_id     TEXT PRIMARY KEY,
            canonical_id TEXT NOT NULL,
            session_id   TEXT NOT NULL,
            source       TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_occ_session ON paper_occurrences(session_id);
        CREATE INDEX IF NOT EXISTS idx_occ_canonical ON paper_occurrences(canonical_id);
        """
    )
    return conn


# --- the key ----------------------------------------------------------------------

def _clean(value) -> str:
    return (value or "").strip() if isinstance(value, str) else ""


def canonical_key(paper: dict) -> tuple[str, str] | None:
    """
    (kind, value) for the strongest identifier this paper has, or None when it
    has none worth trusting -- an untitled record with no identifier is left
    alone rather than merged with every other untitled record.
    """
    doi = _DOI_PREFIX.sub("", _clean(paper.get("doi"))).lower().rstrip("/")
    if doi and "/" in doi:
        return DOI, doi

    arxiv = _ARXIV_PREFIX.sub("", _clean(paper.get("arxiv_id"))).lower()
    arxiv = _ARXIV_VERSION.sub("", arxiv).removesuffix(".pdf")
    if arxiv and not arxiv.startswith(("http", "urn:")):
        return ARXIV, arxiv

    title = unicodedata.normalize("NFKD", _clean(paper.get("title")).lower())
    title = _NOT_WORD.sub("", title)
    if len(title) >= 12:                 # shorter than this is not a title
        return TITLE, title
    return None


def canonical_id(paper: dict) -> str | None:
    key = canonical_key(paper)
    if key is None:
        return None
    kind, value = key
    return hashlib.sha1(f"{kind}:{value}".encode()).hexdigest()[:16]


# --- filing -----------------------------------------------------------------------

def index_paper(session_id: str, paper: dict, db_path: Path | None = None) -> str | None:
    """File one paper row under its canonical record. Returns the canonical id."""
    key = canonical_key(paper)
    if key is None or not _clean(paper.get("paper_id")):
        return None
    kind, value = key
    cid = canonical_id(paper)

    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO canonical_papers (canonical_id, key_kind, key_value, title, authors, "
            "year, url, doi, arxiv_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(canonical_id) DO UPDATE SET "
            # A later sighting may know more than the first one did.
            "title = CASE WHEN length(excluded.title) > length(canonical_papers.title) "
            "             THEN excluded.title ELSE canonical_papers.title END, "
            "authors = CASE WHEN canonical_papers.authors = '' THEN excluded.authors "
            "               ELSE canonical_papers.authors END, "
            "year = COALESCE(canonical_papers.year, excluded.year), "
            "url = CASE WHEN canonical_papers.url = '' THEN excluded.url ELSE canonical_papers.url END, "
            "doi = CASE WHEN canonical_papers.doi = '' THEN excluded.doi ELSE canonical_papers.doi END, "
            "arxiv_id = CASE WHEN canonical_papers.arxiv_id = '' THEN excluded.arxiv_id "
            "                ELSE canonical_papers.arxiv_id END",
            (cid, kind, value, _clean(paper.get("title")), _clean(paper.get("authors")),
             paper.get("year"), _clean(paper.get("url")), _clean(paper.get("doi")),
             _clean(paper.get("arxiv_id"))))
        conn.execute(
            "INSERT INTO paper_occurrences (paper_id, canonical_id, session_id, source) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(paper_id) DO UPDATE SET canonical_id = excluded.canonical_id",
            (paper["paper_id"], cid, session_id, _clean(paper.get("source"))))
        conn.commit()
    finally:
        conn.close()
    return cid


def ensure_indexed(session_ids: list[str], db_path: Path | None = None) -> int:
    """
    File anything not filed yet. Papers collected before this index existed are
    only noticed here, so every read goes through this first.
    """
    if not session_ids:
        return 0
    conn = _connect(db_path)
    try:
        marks = ",".join("?" * len(session_ids))
        rows = conn.execute(
            f"SELECT p.* FROM papers p LEFT JOIN paper_occurrences o ON o.paper_id = p.paper_id "
            f"WHERE p.session_id IN ({marks}) AND o.paper_id IS NULL", session_ids).fetchall()
    except sqlite3.OperationalError:               # no papers table yet
        return 0
    finally:
        conn.close()
    filed = 0
    for row in rows:
        if index_paper(row["session_id"], dict(row), db_path=db_path):
            filed += 1
    if filed:
        logger.info("Filed %d paper(s) into the canonical index.", filed)
    return filed


# --- reading ----------------------------------------------------------------------

def count_for(session_ids: list[str], db_path: Path | None = None) -> int:
    """How many distinct papers these sessions rest on."""
    if not session_ids:
        return 0
    ensure_indexed(session_ids, db_path=db_path)
    conn = _connect(db_path)
    try:
        marks = ",".join("?" * len(session_ids))
        row = conn.execute(
            f"SELECT COUNT(DISTINCT canonical_id) n FROM paper_occurrences "
            f"WHERE session_id IN ({marks})", session_ids).fetchone()
    finally:
        conn.close()
    return row["n"] or 0


def library(session_ids: list[str], db_path: Path | None = None) -> list[dict]:
    """
    Every distinct paper these sessions have read, most-used first, each with
    the sessions that used it. This is what a project's reading list is.
    """
    if not session_ids:
        return []
    ensure_indexed(session_ids, db_path=db_path)
    conn = _connect(db_path)
    try:
        marks = ",".join("?" * len(session_ids))
        rows = conn.execute(
            f"SELECT c.*, COUNT(DISTINCT o.session_id) sessions, "
            f"       GROUP_CONCAT(DISTINCT o.session_id) session_ids "
            f"FROM canonical_papers c JOIN paper_occurrences o ON o.canonical_id = c.canonical_id "
            f"WHERE o.session_id IN ({marks}) "
            f"GROUP BY c.canonical_id ORDER BY sessions DESC, c.year DESC, c.title",
            session_ids).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        paper = dict(r)
        paper["session_ids"] = [s for s in (paper.pop("session_ids") or "").split(",") if s]
        out.append(paper)
    return out


def sessions_sharing(session_ids: list[str], db_path: Path | None = None) -> list[dict]:
    """
    Which pairs of sessions read the same papers, and how many. This is what
    makes a project a body of work rather than a list: it shows where one
    session built on what another had already read.
    """
    if len(session_ids) < 2:
        return []
    ensure_indexed(session_ids, db_path=db_path)
    conn = _connect(db_path)
    try:
        marks = ",".join("?" * len(session_ids))
        rows = conn.execute(
            f"SELECT a.session_id left_id, b.session_id right_id, "
            f"       COUNT(DISTINCT a.canonical_id) shared "
            f"FROM paper_occurrences a JOIN paper_occurrences b "
            f"  ON a.canonical_id = b.canonical_id AND a.session_id < b.session_id "
            f"WHERE a.session_id IN ({marks}) AND b.session_id IN ({marks}) "
            f"GROUP BY a.session_id, b.session_id HAVING shared > 0 ORDER BY shared DESC",
            session_ids + session_ids).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def where_used(canonical: str, db_path: Path | None = None) -> list[str]:
    """Every session that has read this paper."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM paper_occurrences WHERE canonical_id = ?",
            (canonical,)).fetchall()
    finally:
        conn.close()
    return [r["session_id"] for r in rows]
