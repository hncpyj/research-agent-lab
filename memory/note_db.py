"""
SQLite interface for structured metadata: sessions, papers, hypotheses.

Tables:
  research_sessions  — one row per user session
  papers             — collected papers per session
  hypotheses         — generated hypotheses per session
  experiment_code    — generated code files per hypothesis
  experiment_runs    — execution records per phase (Phase 6)
  (api_usage_log is managed by CostTracker)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


class NoteDB:
    """
    All database writes use parameterised queries.
    Connections are opened per-call (SQLite WAL mode makes this safe).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        # Read config at call time, not at import time. As a default argument
        # this was bound once when the module loaded, so a test that pointed
        # config.SQLITE_PATH at a temporary file still wrote to the real
        # database (found 2026-09-21, after tests created 45 sessions in it).
        self._db_path = db_path if db_path is not None else config.SQLITE_PATH
        self._init_schema()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # timeout: with several people using the server, a writer holding the
        # lock for a moment would otherwise raise "database is locked" at once
        # instead of waiting its turn.
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_sessions (
                    session_id         TEXT PRIMARY KEY,
                    topic              TEXT NOT NULL,
                    research_question  TEXT,
                    gap_report         TEXT,
                    status             TEXT NOT NULL DEFAULT 'started',
                    created_at         TEXT NOT NULL,
                    updated_at         TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS papers (
                    paper_id              TEXT PRIMARY KEY,
                    session_id            TEXT NOT NULL,
                    arxiv_id              TEXT NOT NULL,
                    title                 TEXT,
                    authors               TEXT,
                    year                  INTEGER,
                    url                   TEXT,
                    abstract              TEXT,
                    method                TEXT,
                    limitation            TEXT,
                    dataset               TEXT,
                    metric                TEXT,
                    contribution          TEXT,
                    replication_possible  INTEGER DEFAULT 0,
                    code_available        INTEGER DEFAULT 0,
                    created_at            TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES research_sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS hypotheses (
                    hypothesis_id     TEXT PRIMARY KEY,
                    session_id        TEXT NOT NULL,
                    content           TEXT NOT NULL,
                    experiment_design TEXT,
                    feasibility_score REAL,
                    status            TEXT NOT NULL DEFAULT 'candidate',
                    created_at        TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES research_sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS api_usage_log (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     TEXT    NOT NULL,
                    model         TEXT    NOT NULL,
                    input_tokens  INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd      REAL    NOT NULL,
                    task_type     TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS experiment_code (
                    code_id        TEXT PRIMARY KEY,
                    session_id     TEXT NOT NULL,
                    hypothesis_id  TEXT NOT NULL,
                    file_path      TEXT NOT NULL,
                    file_content   TEXT NOT NULL,
                    language       TEXT NOT NULL DEFAULT 'python',
                    created_at     TEXT NOT NULL,
                    UNIQUE (hypothesis_id, file_path),
                    FOREIGN KEY (session_id)    REFERENCES research_sessions(session_id),
                    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(hypothesis_id)
                );

                CREATE TABLE IF NOT EXISTS experiment_runs (
                    run_id         TEXT PRIMARY KEY,
                    session_id     TEXT NOT NULL,
                    hypothesis_id  TEXT NOT NULL,
                    phase          TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    stdout         TEXT,
                    stderr         TEXT,
                    fix_attempts   INTEGER DEFAULT 0,
                    metrics_json   TEXT,
                    started_at     TEXT NOT NULL,
                    finished_at    TEXT,
                    FOREIGN KEY (session_id)    REFERENCES research_sessions(session_id),
                    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(hypothesis_id)
                );

                CREATE TABLE IF NOT EXISTS degradations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    phase       INTEGER NOT NULL,
                    component   TEXT NOT NULL,
                    severity    TEXT NOT NULL,
                    message     TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES research_sessions(session_id)
                );
                """
            )
            # One row per version of a stage document (data audit, hypotheses,
            # analysis plan, results table, claims, review). A stage counts as
            # done only through its latest row's status.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_artifacts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    stage       TEXT NOT NULL,
                    version     INTEGER NOT NULL,
                    status      TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    approved    INTEGER NOT NULL DEFAULT 0,
                    note        TEXT,
                    created_at  TEXT NOT NULL
                )
                """
            )
            # Migrate older databases: add columns that may be missing
            self._migrate_schema(conn)
        logger.debug("SQLite schema ready at %s", self._db_path)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after initial release (idempotent)."""
        migrations = [
            "ALTER TABLE research_sessions ADD COLUMN gap_report TEXT",
            "ALTER TABLE research_sessions ADD COLUMN background TEXT",
            "ALTER TABLE research_sessions ADD COLUMN goals TEXT",
            "ALTER TABLE research_sessions ADD COLUMN constraints TEXT",
            "ALTER TABLE research_sessions ADD COLUMN quality_review TEXT",
            "ALTER TABLE research_sessions ADD COLUMN report TEXT",
            "ALTER TABLE research_sessions ADD COLUMN gap_validation TEXT",
            # Who this research belongs to. Empty means it was made before
            # there were accounts; the first account adopts those.
            "ALTER TABLE research_sessions ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''",
            # Which project this session is filed under; empty means none yet.
            "ALTER TABLE research_sessions ADD COLUMN project_id TEXT NOT NULL DEFAULT ''",
            # Model-inference permission and selected BYOK provider belong to
            # the session, so refresh, reconnect and resume cannot change them.
            "ALTER TABLE research_sessions ADD COLUMN model_api_enabled INTEGER",
            "ALTER TABLE research_sessions ADD COLUMN model_provider TEXT",
            "ALTER TABLE hypotheses ADD COLUMN domain TEXT",
            "ALTER TABLE papers ADD COLUMN doi TEXT",
            "ALTER TABLE papers ADD COLUMN source TEXT",
            "ALTER TABLE papers ADD COLUMN fulltext_id TEXT",
            "ALTER TABLE papers ADD COLUMN future_work TEXT",
            "ALTER TABLE papers ADD COLUMN findings TEXT",
            "ALTER TABLE papers ADD COLUMN text_source TEXT",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

    # ------------------------------------------------------------------
    # Session operations
    # ------------------------------------------------------------------

    def create_session(
        self,
        topic: str,
        background: str = "",
        goals: str = "",
        constraints: str = "",
        owner_id: str = "",
        project_id: str = "",
        model_api_enabled: bool | None = None,
        model_provider: str = "",
    ) -> str:
        session_id = str(uuid.uuid4())
        ts = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_sessions
                    (session_id, topic, status, created_at, updated_at,
                     background, goals, constraints, owner_id, project_id,
                     model_api_enabled, model_provider)
                VALUES (?, ?, 'started', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    topic,
                    ts,
                    ts,
                    background,
                    goals,
                    constraints,
                    owner_id,
                    project_id,
                    None if model_api_enabled is None else int(model_api_enabled),
                    model_provider or "",
                ),
            )
        logger.info("Session created: %s", session_id)
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id: str, **kwargs) -> None:
        """Update arbitrary columns on a session row."""
        kwargs["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [session_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE research_sessions SET {set_clause} WHERE session_id = ?",
                values,
            )

    def list_sessions(self, owner_id: str | None = None) -> list[dict]:
        """
        Sessions, newest first. With an owner_id, only that person's — the
        default (None) is the local single-user mode, where everything on the
        machine belongs to whoever is at the keyboard.
        """
        with self._connect() as conn:
            if owner_id is None:
                rows = conn.execute(
                    "SELECT * FROM research_sessions ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_sessions WHERE owner_id = ? ORDER BY created_at DESC",
                    (owner_id,)).fetchall()
        return [dict(r) for r in rows]

    def session_owner(self, session_id: str) -> str | None:
        """The owner's id, "" for sessions made before accounts, None if no such session."""
        with self._connect() as conn:
            row = conn.execute("SELECT owner_id FROM research_sessions WHERE session_id = ?",
                               (session_id,)).fetchone()
        return (row["owner_id"] or "") if row else None

    # ------------------------------------------------------------------
    # Paper operations
    # ------------------------------------------------------------------

    def save_paper(self, session_id: str, paper: dict) -> str:
        """
        Insert a paper record, or update it in place if a paper with the
        same (session_id, arxiv_id) already exists.

        `paper` should include at minimum: arxiv_id, title. Returns the
        paper_id.

        This used to always generate a fresh paper_id and rely on
        `INSERT OR REPLACE` to dedupe — but with a brand-new random id on
        every call, that INSERT never actually conflicted with anything, so
        every call (e.g. literature_review.py re-saving a paper once its
        method/limitation/dataset fields are extracted) silently produced a
        second, duplicate row instead of updating the first. Looking up the
        existing row by (session_id, arxiv_id) first fixes that.
        """
        ts = _now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT paper_id FROM papers WHERE session_id = ? AND arxiv_id = ?",
                (session_id, paper.get("arxiv_id", "")),
            ).fetchone()
            paper_id = existing["paper_id"] if existing else str(uuid.uuid4())
            conn.execute(
                """
                INSERT OR REPLACE INTO papers (
                    paper_id, session_id, arxiv_id, title, authors, year, url,
                    abstract, method, limitation, dataset, metric, contribution,
                    replication_possible, code_available, created_at,
                    doi, source, fulltext_id, future_work, findings, text_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    session_id,
                    paper.get("arxiv_id", ""),
                    paper.get("title", ""),
                    paper.get("authors", ""),
                    paper.get("year"),
                    paper.get("url", ""),
                    paper.get("abstract", ""),
                    paper.get("method", ""),
                    paper.get("limitation", ""),
                    paper.get("dataset", ""),
                    paper.get("metric", ""),
                    paper.get("contribution", ""),
                    int(paper.get("replication_possible", False)),
                    int(paper.get("code_available", False)),
                    ts,
                    paper.get("doi", ""),
                    paper.get("source", ""),
                    paper.get("fulltext_id", ""),
                    paper.get("future_work", ""),
                    paper.get("findings", ""),
                    paper.get("text_source", ""),
                ),
            )
        # File it under its canonical record, so a project can say how many
        # distinct papers it rests on and which ones it keeps returning to.
        try:
            from memory import paper_index
            paper_index.index_paper(session_id, {**paper, "paper_id": paper_id},
                                    db_path=self._db_path)
        except Exception as exc:                  # indexing must never lose a paper
            logger.warning("Could not index paper %s: %s", paper_id, exc)
        return paper_id

    def get_papers(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                # rowid breaks ties between rows saved in the same second, so the
                # order matches the [n] numbering the gap report cites.
                "SELECT * FROM papers WHERE session_id = ? ORDER BY created_at, rowid",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def paper_exists(self, session_id: str, arxiv_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM papers WHERE session_id = ? AND arxiv_id = ?",
                (session_id, arxiv_id),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Degradation log — records every best-effort path that silently fell
    # back to something weaker (canon seeding unavailable, ranking unable
    # to run, evidence fabricated). See agents/degradation.py.
    # ------------------------------------------------------------------

    def save_degradation(
        self, session_id: str, phase: int, component: str, severity: str, message: str
    ) -> int:
        ts = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO degradations
                    (session_id, phase, component, severity, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, phase, component, severity, message, ts),
            )
        return cur.lastrowid

    def get_degradations(
        self, session_id: str, phase: int | None = None
    ) -> list[dict]:
        query = "SELECT * FROM degradations WHERE session_id = ?"
        params: list = [session_id]
        if phase is not None:
            query += " AND phase = ?"
            params.append(phase)
        query += " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stage documents
    # ------------------------------------------------------------------

    ARTIFACT_STATUSES = ("passed", "failed", "blocked", "awaiting_approval")

    def save_artifact(self, session_id: str, stage: str, content: dict, status: str, note: str = "") -> int:
        """Store a new version of a stage document. Returns its version number."""
        if status not in self.ARTIFACT_STATUSES:
            raise ValueError(f"unknown artifact status {status!r}")
        import hashlib
        text = json.dumps(content, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM research_artifacts WHERE session_id = ? AND stage = ?",
                (session_id, stage)).fetchone()
            version = row[0] + 1
            conn.execute(
                """
                INSERT INTO research_artifacts
                    (session_id, stage, version, status, content, content_hash, approved, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (session_id, stage, version, status, text, digest, note, _now()))
        return version

    def get_artifact(self, session_id: str, stage: str) -> dict | None:
        """Latest version of a stage document, with content decoded; None if none exists."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_artifacts WHERE session_id = ? AND stage = ? ORDER BY version DESC LIMIT 1",
                (session_id, stage)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["content"] = json.loads(d["content"])
        d["approved"] = bool(d["approved"])
        return d

    def list_artifacts(self, session_id: str) -> list[dict]:
        """Latest version of every stage document for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.* FROM research_artifacts a
                JOIN (SELECT stage, MAX(version) v FROM research_artifacts WHERE session_id = ? GROUP BY stage) m
                  ON a.stage = m.stage AND a.version = m.v
                WHERE a.session_id = ? ORDER BY a.id
                """, (session_id, session_id)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["content"] = json.loads(d["content"])
            d["approved"] = bool(d["approved"])
            out.append(d)
        return out

    def approve_artifact(self, session_id: str, stage: str, version: int, status: str = "passed") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE research_artifacts SET approved = 1, status = ? WHERE session_id = ? AND stage = ? AND version = ?",
                (status, session_id, stage, version))

    # ------------------------------------------------------------------
    # Hypothesis operations
    # ------------------------------------------------------------------

    def save_hypothesis(
        self,
        session_id: str,
        content: str,
        experiment_design: dict | None = None,
        feasibility_score: float | None = None,
    ) -> str:
        hypothesis_id = str(uuid.uuid4())
        ts = _now()
        design_json = json.dumps(experiment_design) if experiment_design else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO hypotheses
                    (hypothesis_id, session_id, content, experiment_design,
                     feasibility_score, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'candidate', ?)
                """,
                (hypothesis_id, session_id, content, design_json,
                 feasibility_score, ts),
            )
        return hypothesis_id

    def get_hypotheses(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hypotheses WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("experiment_design"):
                d["experiment_design"] = json.loads(d["experiment_design"])
            result.append(d)
        return result

    def update_hypothesis_status(
        self, hypothesis_id: str, status: str, domain: str | None = None
    ) -> None:
        """
        Update status and, when known, the domain the experiment codebase was
        generated under (e.g. "reinforcement learning", "nlp") — persisted so
        which domain-routing decision produced a given file set is auditable
        later without reconstructing it from file names.
        """
        with self._connect() as conn:
            if domain is not None:
                conn.execute(
                    "UPDATE hypotheses SET status = ?, domain = ? WHERE hypothesis_id = ?",
                    (status, domain, hypothesis_id),
                )
            else:
                conn.execute(
                    "UPDATE hypotheses SET status = ? WHERE hypothesis_id = ?",
                    (status, hypothesis_id),
                )

    # ------------------------------------------------------------------
    # Experiment code operations
    # ------------------------------------------------------------------

    def save_experiment_code(
        self,
        session_id: str,
        hypothesis_id: str,
        file_path: str,
        file_content: str,
        language: str = "python",
    ) -> str:
        """
        Insert or replace a generated experiment code file.
        The UNIQUE constraint on (hypothesis_id, file_path) ensures
        that re-generating a file overwrites the previous version.
        Returns the code_id (UUID).
        """
        code_id = str(uuid.uuid4())
        ts = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiment_code
                    (code_id, session_id, hypothesis_id, file_path,
                     file_content, language, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (code_id, session_id, hypothesis_id,
                 file_path, file_content, language, ts),
            )
        logger.debug("Saved experiment code: %s", file_path)
        return code_id

    def get_experiment_code(self, hypothesis_id: str) -> list[dict]:
        """Return all generated files for a given hypothesis, ordered by file_path."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM experiment_code
                WHERE hypothesis_id = ?
                ORDER BY file_path
                """,
                (hypothesis_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session_experiment_code(self, session_id: str) -> list[dict]:
        """Return all generated files across all hypotheses for a session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM experiment_code
                WHERE session_id = ?
                ORDER BY hypothesis_id, file_path
                """,
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Experiment run operations  (Phase 6)
    # ------------------------------------------------------------------

    def create_experiment_run(
        self,
        session_id: str,
        hypothesis_id: str,
        phase: str,
    ) -> str:
        """
        Insert a new run record in 'running' state.
        phase: one of 'install' | 'pretrain' | 'train' | 'evaluate'
        Returns the run_id (UUID).
        """
        run_id = str(uuid.uuid4())
        ts = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO experiment_runs
                    (run_id, session_id, hypothesis_id, phase, status,
                     stdout, stderr, fix_attempts, metrics_json,
                     started_at, finished_at)
                VALUES (?, ?, ?, ?, 'running', NULL, NULL, 0, NULL, ?, NULL)
                """,
                (run_id, session_id, hypothesis_id, phase, ts),
            )
        logger.debug("Experiment run created: %s phase=%s", run_id, phase)
        return run_id

    def finish_experiment_run(
        self,
        run_id: str,
        status: str,
        stdout: str = "",
        stderr: str = "",
        fix_attempts: int = 0,
        metrics: dict | None = None,
    ) -> None:
        """
        Update a run record with final status and captured output.
        status: 'success' | 'failed' | 'fixed'
        """
        ts = _now()
        metrics_json = json.dumps(metrics) if metrics else None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE experiment_runs
                SET status       = ?,
                    stdout       = ?,
                    stderr       = ?,
                    fix_attempts = ?,
                    metrics_json = ?,
                    finished_at  = ?
                WHERE run_id = ?
                """,
                (status, stdout, stderr, fix_attempts, metrics_json, ts, run_id),
            )
        logger.debug("Experiment run finished: %s status=%s", run_id, status)

    def get_experiment_runs(self, session_id: str) -> list[dict]:
        """Return all run records for a session, ordered by started_at."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM experiment_runs
                WHERE session_id = ?
                ORDER BY started_at
                """,
                (session_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("metrics_json"):
                import re as _re
                safe_mj = _re.sub(r'\bNaN\b', 'null', d["metrics_json"])
                safe_mj = _re.sub(r'\bInfinity\b', 'null', safe_mj)
                safe_mj = _re.sub(r'\b-Infinity\b', 'null', safe_mj)
                d["metrics"] = json.loads(safe_mj)
            result.append(d)
        return result

    def get_latest_run(self, session_id: str, phase: str) -> dict | None:
        """
        Return the most recent run record for a given session+phase.
        Used by the runner to check whether a phase already succeeded
        (resume support).
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM experiment_runs
                WHERE session_id = ? AND phase = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (session_id, phase),
            ).fetchone()
        return dict(row) if row else None
