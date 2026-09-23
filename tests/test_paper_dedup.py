"""
Regression test for save_paper() upserting by (session_id, arxiv_id)
(memory/note_db.py).

Background: save_paper() always generated a fresh random paper_id and
relied on `INSERT OR REPLACE` to dedupe. Since a brand-new UUID never
conflicts with anything, every call — including literature_review.py
re-saving a paper once its method/limitation/dataset fields are extracted
— silently produced a second row instead of updating the first. A
2026-09-12 test session's `papers` table had exactly 2x as many rows as
papers shown in the UI: the first 20 bare (from Phase 1), a second set of
20 with the same arxiv_ids fully populated (from Phase 2), because the
second save() never found a match.
"""
import shutil
import tempfile
from pathlib import Path

from memory.note_db import NoteDB


def _temp_db():
    tmp_dir = tempfile.mkdtemp()
    db = NoteDB(db_path=Path(tmp_dir) / "test.db")
    return db, tmp_dir


def test_resaving_the_same_paper_updates_in_place_not_a_duplicate_row():
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")

        # Phase 1: bare save
        db.save_paper(session_id, {"arxiv_id": "1234.5678", "title": "A Paper"})
        # Phase 2: re-save with extracted fields, same session + arxiv_id
        db.save_paper(session_id, {
            "arxiv_id": "1234.5678", "title": "A Paper",
            "method": "does X", "limitation": "doesn't do Y",
        })

        papers = db.get_papers(session_id)
        assert len(papers) == 1  # not 2
        assert papers[0]["method"] == "does X"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_resave_preserves_the_same_paper_id():
    """Downstream references by paper_id (if any) must not be orphaned by
    a re-save silently minting a new id."""
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")

        first_id = db.save_paper(session_id, {"arxiv_id": "1234.5678", "title": "A Paper"})
        second_id = db.save_paper(session_id, {"arxiv_id": "1234.5678", "title": "A Paper (updated)"})

        assert first_id == second_id
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_same_arxiv_id_in_different_sessions_are_independent_rows():
    """The dedup key is (session_id, arxiv_id) — the same paper collected
    in two different sessions must not collide."""
    db, tmp_dir = _temp_db()
    try:
        s1 = db.create_session("topic 1")
        s2 = db.create_session("topic 2")

        db.save_paper(s1, {"arxiv_id": "1234.5678", "title": "A Paper"})
        db.save_paper(s2, {"arxiv_id": "1234.5678", "title": "A Paper"})

        assert len(db.get_papers(s1)) == 1
        assert len(db.get_papers(s2)) == 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
