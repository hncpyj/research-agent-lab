"""
The CLI runs the same study stages as the web UI.

2026-09-20 backlog: the gated pipeline only existed behind the web UI, so
`python main.py` still ran the old ML-template phases on a brief that
declares its own dataset.
"""
import pytest

import config
from memory.note_db import NoteDB
from ui.console_runner import ConsoleRunner, run_study


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    return NoteDB(tmp_path / "t.db")


def test_gate_answers_come_from_the_terminal(monkeypatch):
    runner = ConsoleRunner("s1")
    answers = iter(["H1, H3", "", "y"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    assert runner.wait_for_input("hypothesis_selection", "pick") == ["H1", "H3"]
    assert runner.waiting_step is None

    monkeypatch.setattr("ui.console_runner.ConsoleRunner._plan_text", lambda self, path: "TEST: H1.T1")
    assert runner.wait_for_input("plan_approval", "approve") == {"text": "TEST: H1.T1", "approve": True}


def test_an_edited_plan_file_is_read(tmp_path, monkeypatch):
    plan = tmp_path / "plan.txt"
    plan.write_text("TEST: H1.T1\nBLOCK: correlation", encoding="utf-8")
    runner = ConsoleRunner("s1")
    answers = iter([str(plan), "n"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    reply = runner.wait_for_input("plan_approval", "approve")
    assert reply == {"text": "TEST: H1.T1\nBLOCK: correlation", "approve": False}


def test_stopping_at_a_gate_stops_the_study(monkeypatch):
    from ui.study_runner import StudyStopped

    runner = ConsoleRunner("s1")
    def _interrupt(*a): raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _interrupt)

    with pytest.raises(StudyStopped):
        runner.wait_for_input("hypothesis_selection", "pick")
    assert runner._stop_flag.is_set()


def test_a_brief_without_a_dataset_is_left_to_the_old_phases(db):
    sid = db.create_session("transformer attention", background="no dataset here")
    assert run_study(sid, db, None) is None        # None = "not mine to run"


def test_a_declared_dataset_that_cannot_be_read_stops_instead_of_falling_back(db, monkeypatch):
    from agents.data_audit import DataAuditError

    sid = db.create_session("clean cooking", background="data: https://example.org/data.zip")
    monkeypatch.setattr("agents.data_audit.declared_dataset",
                        lambda session: (_ for _ in ()).throw(DataAuditError("404 downloading data.zip")))

    assert run_study(sid, db, None) is False
    art = db.get_artifact(sid, "data_audit")
    assert art["status"] == "blocked" and "404" in art["content"]["error"]
