"""
Cost tracker: logs every API call to the SQLite api_usage_log table
and provides running totals.
"""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import config

logger = logging.getLogger(__name__)

# Cost per 1 M tokens (USD) — see config.TOKEN_COSTS
_COSTS = config.TOKEN_COSTS


def _get_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Price one call. A model with no published rate in config.TOKEN_COSTS is
    costed at the deliberately high UNKNOWN_TOKEN_COST and said so in the log:
    a daily cap that guesses low is worse than one that stops early, and this
    used to price any non-Claude model at Claude Sonnet's rate silently.
    """
    rates = _COSTS.get(model)
    if rates is None:
        rates = config.UNKNOWN_TOKEN_COST
        logger.warning("No published price for %s; costing it at $%.2f/$%.2f per 1M tokens. "
                       "Add it to config.TOKEN_COSTS for a real figure.",
                       model, rates["input"], rates["output"])
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


class CostTracker:
    """
    Thread-safe (via SQLite WAL) cost tracker that persists to the same
    SQLite database used by the rest of the application.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        # Resolved now, not at import time — see the note in memory/note_db.py.
        self._db_path = db_path if db_path is not None else config.SQLITE_PATH
        self._init_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        task_type: str,
        is_local: bool = False,
        session_id: str = "",
    ) -> float:
        """
        Insert one record and return the USD cost for this call.

        `is_local=True` forces cost to $0 and should be used for local-model
        fallback calls (see APIModel._local_fallback) — without this, a call
        made through the local model would still get priced using
        config.TOKEN_COSTS' default rate (since the model string won't match
        any known Claude model), silently inflating the reported spend for a
        call that cost nothing.

        This table is the only persisted record of "which backend actually
        served this request" — an audit found that when the Anthropic API
        silently becomes unavailable mid-run, APIModel falls back to the
        local model with NO record of the fact anywhere for the rest of that
        session, making it indistinguishable after the fact from paid API
        usage that just didn't get logged. Every generate() call — API or
        local — must produce exactly one row here.
        """
        cost = 0.0 if is_local else _get_cost(model, input_tokens, output_tokens)
        ts = datetime.utcnow().isoformat(timespec="seconds")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_usage_log
                    (timestamp, model, input_tokens, output_tokens, cost_usd, task_type, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, model, input_tokens, output_tokens, cost, task_type, session_id or ""),
            )

        logger.debug(
            "API call logged: model=%s task=%s in=%d out=%d cost=$%.4f",
            model, task_type, input_tokens, output_tokens, cost,
        )
        return cost

    def call_count(self, since_timestamp: Optional[str] = None) -> int:
        """
        Total logged calls (API + local fallback) since `since_timestamp`
        (ISO string), or all-time if omitted. Used by the pipeline-end
        healthcheck to catch the case a phase completed with zero logged
        calls at all — the exact failure mode this table exists to prevent.
        """
        query = "SELECT COUNT(*) FROM api_usage_log"
        params: list = []
        if since_timestamp:
            query += " WHERE timestamp >= ?"
            params.append(since_timestamp)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return row[0] or 0

    def total_cost(self) -> float:
        """Return total USD spent across all sessions."""
        with self._connect() as conn:
            row = conn.execute("SELECT SUM(cost_usd) FROM api_usage_log").fetchone()
        return row[0] or 0.0

    def session_cost(self, session_id: str) -> dict:
        """
        What one session cost. The session view used to show the all-time
        total here, so a session that spent nothing looked expensive; the
        figure for everything together belongs on the dashboard.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) calls, SUM(cost_usd) cost, "
                "SUM(CASE WHEN model LIKE 'local:%' THEN 1 ELSE 0 END) local_calls "
                "FROM api_usage_log WHERE session_id = ?", (session_id,)).fetchone()
        calls = row[0] or 0
        return {"cost_usd": row[1] or 0.0, "calls": calls, "local_calls": row[2] or 0,
                "attributed": calls > 0}

    def spend_since(self, since_timestamp: str) -> float:
        """USD spent since an ISO timestamp."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(cost_usd) FROM api_usage_log WHERE timestamp >= ?",
                (since_timestamp,),
            ).fetchone()
        return row[0] or 0.0

    def spend_today(self) -> float:
        """
        USD spent since midnight. This is what the daily cap is measured
        against: a loop that keeps retrying cannot spend more than a day's
        budget, and the cap survives a restart because the figure is read
        back from this table rather than counted in memory.
        """
        # Rows are stamped with utcnow(), so the day boundary is UTC too —
        # comparing against local midnight would drop or double-count the
        # rows written within the machine's offset from UTC.
        return self.spend_since(datetime.utcnow().strftime("%Y-%m-%dT00:00:00"))

    def session_summary(self, since_timestamp: Optional[str] = None) -> dict:
        """
        Return a summary dict:
          { task_type -> {calls, input_tokens, output_tokens, cost_usd} }
        Optionally filtered to rows after `since_timestamp` (ISO string).
        """
        query = "SELECT task_type, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) FROM api_usage_log"
        params: list = []
        if since_timestamp:
            query += " WHERE timestamp >= ?"
            params.append(since_timestamp)
        query += " GROUP BY task_type"

        result: dict = {}
        with self._connect() as conn:
            for row in conn.execute(query, params):
                task, calls, inp, out, cost = row
                result[task] = {
                    "calls": calls,
                    "input_tokens": inp or 0,
                    "output_tokens": out or 0,
                    "cost_usd": cost or 0.0,
                }
        return result

    def print_summary(self) -> None:
        """Pretty-print a cost summary to stdout using rich."""
        from rich.console import Console
        from rich.table import Table

        summary = self.session_summary()
        total = self.total_cost()

        console = Console()
        table = Table(title="API Cost Summary", show_lines=True)
        table.add_column("Task Type", style="cyan")
        table.add_column("Calls", justify="right")
        table.add_column("Input Tokens", justify="right")
        table.add_column("Output Tokens", justify="right")
        table.add_column("Cost (USD)", justify="right", style="yellow")

        for task, stats in sorted(summary.items()):
            table.add_row(
                task,
                str(stats["calls"]),
                f"{stats['input_tokens']:,}",
                f"{stats['output_tokens']:,}",
                f"${stats['cost_usd']:.4f}",
            )

        console.print(table)
        console.print(f"[bold yellow]Total API spend: ${total:.4f}[/]")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_usage_log (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     TEXT    NOT NULL,
                    model         TEXT    NOT NULL,
                    input_tokens  INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd      REAL    NOT NULL,
                    task_type     TEXT    NOT NULL,
                    session_id    TEXT    NOT NULL DEFAULT ''
                )
                """
            )
            # Existing databases predate the session column; rows already in
            # them stay unattributed rather than being guessed at.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(api_usage_log)")}
            if "session_id" not in columns:
                conn.execute("ALTER TABLE api_usage_log ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_session ON api_usage_log(session_id)")
