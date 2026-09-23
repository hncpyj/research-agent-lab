"""
Two M8 gaps closed on 2026-09-20.

A brief that says to rely on a paper source used to run anyway on whatever
was reachable, recording the substitution but never asking; and a gap report
stayed on screen looking current after the brief or the paper set changed.
"""
import pytest

import config
from agents.gap_analysis import gap_staleness, record_gap_context
from memory.note_db import NoteDB
from ui.study_runner import apply_source_decision


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    database = NoteDB(tmp_path / "t.db")
    return database


# --- the blocked-source gate ---------------------------------------------------

PROBLEM = "The brief asks to rely on semantic scholar, but that source is blocked until 2026-09-27 00:00 UTC."


def test_continuing_without_the_source_is_recorded_as_a_decision(db):
    sid = db.create_session("t")
    db.save_artifact(sid, "source_check", {"problems": [PROBLEM]}, "awaiting_approval")

    proceeding, message = apply_source_decision(db, sid, True)
    art = db.get_artifact(sid, "source_check")

    assert proceeding and "limitation" in message
    assert art["status"] == "passed" and art["approved"]
    assert art["content"]["decision"] == "proceed"


def test_stopping_leaves_the_study_blocked(db):
    sid = db.create_session("t")
    db.save_artifact(sid, "source_check", {"problems": [PROBLEM]}, "awaiting_approval")

    proceeding, message = apply_source_decision(db, sid, False)
    art = db.get_artifact(sid, "source_check")

    assert not proceeding and "Stopped" in message
    assert art["status"] == "blocked" and art["content"]["decision"] == "stop"


def test_a_session_with_no_open_source_question_refuses_a_decision(db):
    sid = db.create_session("t")
    proceeding, message = apply_source_decision(db, sid, True)
    assert not proceeding and "not waiting" in message


def test_the_pipeline_stops_when_the_user_says_stop(db, monkeypatch):
    """The gate is a real stop, not a notice: the study does not go on to the audit."""
    from ui.study_runner import StudyPipeline

    sid = db.create_session("clean cooking", background="Rely on the Semantic Scholar canon seeding path")

    class _Runner:
        session_id = sid
        waiting_step = None
        _stop_flag = type("F", (), {"is_set": staticmethod(lambda: False)})()
        events: list = []
        def emit(self, kind, data=None): self.events.append((kind, data or {}))
        def wait_for_input(self, step, message): return {"proceed": False}

    class _Limiter:
        def blocked_until(self, source): return 1_800_000_000.0 if source == "semantic_scholar" else 0

    monkeypatch.setattr("tools.rate_limit.get_limiter", lambda: _Limiter())
    runner = _Runner()
    pipeline = StudyPipeline(runner, db, None, ("u", None, None))

    assert pipeline._check_required_sources(db.get_session(sid)) is False
    assert db.get_artifact(sid, "source_check")["status"] == "blocked"
    assert any(kind == "study_blocked" for kind, _ in runner.events)


# --- stale gap reports ----------------------------------------------------------

def _with_report(db, **session):
    sid = db.create_session(session.pop("topic", "clean cooking"), **session)
    db.save_paper(sid, {"arxiv_id": "p1", "title": "One", "authors": "A", "year": 2020, "abstract": ""})
    db.update_session(sid, gap_report="## Gaps\nSomething is missing.")
    record_gap_context(db, sid)
    return sid


def test_an_untouched_gap_report_is_not_marked(db):
    sid = _with_report(db)
    assert gap_staleness(db, sid) == ""


def test_new_papers_make_the_gap_report_stale(db):
    sid = _with_report(db)
    db.save_paper(sid, {"arxiv_id": "p2", "title": "Two", "authors": "B", "year": 2021, "abstract": ""})
    message = gap_staleness(db, sid)
    assert "paper set changed (1 → 2 papers)" in message
    assert "Re-run the gap analysis" in message


def test_editing_the_brief_makes_the_gap_report_stale(db):
    sid = _with_report(db, background="original")
    db.update_session(sid, background="a different question entirely")
    assert "the brief was edited" in gap_staleness(db, sid)


def test_a_session_with_no_gap_report_says_nothing(db):
    sid = db.create_session("t")
    assert gap_staleness(db, sid) == ""
