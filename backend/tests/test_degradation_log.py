"""
Regression tests for the degradation log (agents/degradation.py,
memory/note_db.py's degradations table).

Background: three separate 2026-09-12 incidents (silent cost-log gaps,
silent canon-seeding failure, silent ranking no-op) all had the same shape
— a best-effort fallback path failed and nothing downstream ever learned
about it. DegradationLog exists so "best-effort, never blocks the
pipeline" stops meaning "never tells anyone."
"""
import shutil
import tempfile
from pathlib import Path

from agents.degradation import DegradationLog
from memory.note_db import NoteDB


def _temp_db():
    tmp_dir = tempfile.mkdtemp()
    db = NoteDB(db_path=Path(tmp_dir) / "test.db")
    return db, tmp_dir


def test_record_persists_and_is_readable_back():
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")
        log = DegradationLog(db, session_id)

        log.record(1, "canon_seeding", "critical", "Semantic Scholar returned 0 papers.")

        items = log.for_phase(1)
        assert len(items) == 1
        assert items[0]["component"] == "canon_seeding"
        assert items[0]["severity"] == "critical"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_for_phase_scopes_to_the_requested_phase_only():
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")
        log = DegradationLog(db, session_id)
        log.record(1, "canon_seeding", "critical", "phase 1 issue")
        log.record(3, "gap_validation", "critical", "phase 3 issue")

        assert len(log.for_phase(1)) == 1
        assert len(log.for_phase(3)) == 1
        assert log.for_phase(1)[0]["component"] == "canon_seeding"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_summary_for_prompt_is_injectable_text():
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")
        log = DegradationLog(db, session_id)
        log.record(1, "ranking", "critical", "Papers are UNRANKED.")

        summary = log.summary_for_prompt(phase=1)

        assert "critical" in summary
        assert "ranking" in summary
        assert "UNRANKED" in summary
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_summary_for_prompt_reports_clean_state_with_no_degradations():
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")
        log = DegradationLog(db, session_id)

        assert log.summary_for_prompt() == "No degradations recorded."
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_has_critical_true_only_when_a_critical_entry_exists():
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")
        log = DegradationLog(db, session_id)
        assert log.has_critical() is False

        log.record(1, "relevance_floor", "warn", "only 6 of 40 cleared the floor")
        assert log.has_critical() is False

        log.record(1, "canon_seeding", "critical", "0 papers returned")
        assert log.has_critical() is True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_notify_callback_is_invoked_with_plain_text():
    """notify may be a raw WebSocket log emitter that doesn't understand
    rich markup — record() must not embed any [style]...[/] tags."""
    db, tmp_dir = _temp_db()
    seen = []
    try:
        session_id = db.create_session("test topic")
        log = DegradationLog(db, session_id, notify=seen.append)

        log.record(1, "canon_seeding", "critical", "0 papers returned")

        assert len(seen) == 1
        assert "[" not in seen[0] or "]" not in seen[0].split("[", 1)[1][:1]
        assert "canon_seeding" in seen[0]
        assert "0 papers returned" in seen[0]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_record_never_raises_even_if_note_db_is_broken():
    """The degradation log itself must never be a new way to crash the pipeline."""
    class _BrokenDB:
        def save_degradation(self, *a, **kw):
            raise RuntimeError("simulated DB failure")

    log = DegradationLog(_BrokenDB(), "sess-1")
    log.record(1, "canon_seeding", "critical", "message")  # must not raise


def test_summary_for_prompt_degrades_gracefully_on_a_mock_note_db():
    """Many existing tests pass note_db=MagicMock(); get_degradations() on a
    bare mock returns a non-iterable Mock, not a list — must not crash."""
    from unittest.mock import MagicMock
    log = DegradationLog(MagicMock(), "sess-1")

    assert log.summary_for_prompt() == "No degradations recorded."
    assert log.has_critical() is False
