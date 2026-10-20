"""
The four ways people actually arrive: wanting one stage, not the whole road.

Someone wants only the paper search. Someone has their own papers and wants
the gap analysis. Someone has the question and the data and wants the study
run. Someone has the study and wants the write-up. Each of those is a single
stage plus whatever they bring with them.
"""
import json

import pytest
from fastapi.testclient import TestClient

import config
from memory.note_db import NoteDB

PAPERS_CSV = """title,authors,year,abstract
Clean cooking and health,"Kim, Lee",2021,Households switching fuels report fewer symptoms.
Stacking persists after adoption,"Park",2019,Many households keep using solid fuels alongside gas.
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    monkeypatch.setattr(config, "UI_TOKEN", "")
    import ui.app as ui_app
    ui_app._runners.clear()
    started: list = []

    # No test may start a real pipeline: creating a session normally launches
    # one, which would make paced requests to the paper sources.
    class _NoRunner:
        def __init__(self, **kwargs): self.kwargs = kwargs; self.waiting_step = None
        def start(self): pass
        def is_alive(self): return False
        def stop(self): pass

    monkeypatch.setattr(ui_app, "SessionRunner", _NoRunner)
    monkeypatch.setattr(ui_app, "_start_runner",
                        lambda sid, db, only=None: bool(started.append({"session": sid, "only": only}) or True))
    client = TestClient(ui_app.app)
    client.started = started
    return client


def _new(client, **brief):
    body = {"topic": "clean cooking", **brief}
    return client.post("/api/sessions", json=body).json()["session_id"]


def test_a_fresh_session_offers_only_the_paper_search(client):
    sid = _new(client)

    stages = {s["key"]: s for s in client.get(f"/api/sessions/{sid}/stages").json()["stages"]}
    assert stages["papers"]["ready"] is True
    assert stages["gaps"]["ready"] is False

    assert client.post(f"/api/sessions/{sid}/run/papers").json()["stage"] == "papers"
    assert client.started[-1]["only"] == "papers"


def test_a_stage_that_cannot_run_yet_says_what_is_missing(client):
    sid = _new(client)
    r = client.post(f"/api/sessions/{sid}/run/report")
    assert r.status_code == 409
    assert "results table" in r.json()["detail"]
    assert client.started == []            # nothing was started


def test_an_unknown_stage_is_refused(client):
    sid = _new(client)
    r = client.post(f"/api/sessions/{sid}/run/make-me-famous")
    assert r.status_code == 400 and "Unknown stage" in r.json()["detail"]


def test_bringing_your_own_papers_unlocks_the_gap_stage(client):
    sid = _new(client)
    r = client.post(f"/api/sessions/{sid}/import/papers",
                    json={"text": PAPERS_CSV, "filename": "mine.csv"})
    body = r.json()
    assert r.status_code == 200 and body["imported"] == 2

    stages = {s["key"]: s for s in body["stages"]}
    assert stages["gaps"]["ready"] is True
    assert client.post(f"/api/sessions/{sid}/run/gaps").status_code == 200
    assert client.started[-1]["only"] == "gaps"


def test_a_broken_paper_file_is_refused_with_a_reason(client):
    sid = _new(client)
    r = client.post(f"/api/sessions/{sid}/import/papers", json={"text": "[{oops}]", "filename": "x.json"})
    assert r.status_code == 400 and "not valid JSON" in r.json()["detail"]
    assert NoteDB().get_papers(sid) == []


def test_bringing_your_own_question_and_data_unlocks_the_study(client):
    sid = _new(client, background="The data is at https://example.org/who-gho.zip")
    client.post(f"/api/sessions/{sid}/import/papers", json={"text": PAPERS_CSV, "filename": "mine.csv"})
    r = client.post(f"/api/sessions/{sid}/import/question",
                    json={"text": "Does urban clean fuel use rise faster than rural use?"})
    assert r.status_code == 200

    stages = {s["key"]: s for s in r.json()["stages"]}
    assert stages["audit"]["ready"] is True          # dataset in the brief + a question
    assert stages["hypotheses"]["ready"] is False    # the audit has to run first
    assert client.post(f"/api/sessions/{sid}/run/audit").status_code == 200
    assert client.started[-1]["only"] == "audit"


def test_the_write_up_alone_needs_a_results_table(client):
    sid = _new(client, background="The data is at https://example.org/who-gho.zip")
    db = NoteDB()
    stages = {s["key"]: s for s in client.get(f"/api/sessions/{sid}/stages").json()["stages"]}
    assert stages["report"]["ready"] is False

    db.save_artifact(sid, "results", {"rows": [{"id": "R1", "verdict": "supported"}]}, "passed")
    stages = {s["key"]: s for s in client.get(f"/api/sessions/{sid}/stages").json()["stages"]}
    assert stages["report"]["ready"] is True
    assert client.post(f"/api/sessions/{sid}/run/report").status_code == 200
    assert client.started[-1]["only"] == "report"


def test_a_running_session_is_not_started_twice(client, monkeypatch):
    import ui.app as ui_app
    sid = _new(client)
    ui_app._runners[sid] = type("R", (), {"is_alive": lambda self: True, "waiting_step": None})()
    r = client.post(f"/api/sessions/{sid}/run/papers")
    assert r.status_code == 409 and "already running" in r.json()["detail"]
    ui_app._runners.clear()


def test_imported_work_is_visible_as_imported(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/import/papers", json={"text": PAPERS_CSV, "filename": "mine.csv"})
    client.post(f"/api/sessions/{sid}/import/gap_report",
                json={"text": "Gap: nobody has looked at what happens after the subsidy ends. " * 3})

    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["gap_report"].startswith("> Imported:")
    marks = [d["component"] for d in NoteDB().get_degradations(sid)]
    assert "imported_papers" in marks and "imported_gap_report" in marks
