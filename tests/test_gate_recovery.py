"""
Answering a gate and redoing a stage must work without a running pipeline.

2026-09-20 product audit: after a server restart a session sitting at
"awaiting approval" showed no buttons, because the answer could only be handed
to a waiting thread; and rebuilding a stage meant editing the database by hand
(done five times that day).
"""
import json

import pytest

import config
from memory.note_db import NoteDB
from ui.study_runner import DOWNSTREAM, apply_hypothesis_selection, apply_plan, invalidate

AUDIT = {"indicators": [{"code": "CLEAN", "meaning": "Proportion clean fuels (%)", "unit": "%",
                         "splits": {"Dim1": [{"code": "URB", "meaning": "Urban"}, {"code": "RUR", "meaning": "Rural"}]}}],
         "groups": {}, "limits": [], "source": "x", "question": {"text": "Q?"}}
HYPOTHESES = {"audit_version": 1, "question": "Q?", "selected": [], "hypotheses": [
    {"id": "H1", "statement": "Urban rises faster than rural.", "testable": True, "cannot_test": "", "problems": [],
     "rows": [{"concept": "clean fuel", "variable": "CLEAN", "kind": "indicator", "problem": ""},
              {"concept": "area", "variable": "Dim1:URB,RUR", "kind": "split", "problem": ""}]},
    {"id": "H2", "statement": "Policy raises use.", "testable": False, "problems": ["not in the data"], "rows": []},
]}
PLAN_TEXT = ("TEST: H1.T1\nCOMPARES: urban minus rural trend\nBLOCK: paired_difference\n"
             "PARAMS: indicator=CLEAN; pair=Dim1:URB,RUR; stat=slope\n"
             "SUPPORT_IF: mean > 0 AND ci_low > 0\nREJECT_IF: ci_high < 0\nTHREATS: -")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    database = NoteDB(tmp_path / "t.db")
    sid = database.create_session("t")
    database.save_artifact(sid, "data_audit", AUDIT, "passed")
    database.save_artifact(sid, "hypotheses", HYPOTHESES, "awaiting_approval")
    return database, sid


def test_hypotheses_can_be_chosen_with_no_pipeline_running(db):
    database, sid = db
    accepted, message = apply_hypothesis_selection(database, sid, ["H1"])
    art = database.get_artifact(sid, "hypotheses")
    assert accepted and "H1" in message
    assert art["status"] == "passed" and art["approved"] and art["content"]["selected"] == ["H1"]
    assert database.get_session(sid)["status"] == "hypotheses_selected"
    assert [h["content"] for h in database.get_hypotheses(sid)] == ["Urban rises faster than rural."]


def test_an_untestable_choice_is_refused(db):
    database, sid = db
    accepted, message = apply_hypothesis_selection(database, sid, ["H2"])
    assert not accepted and "H2" in message
    assert database.get_artifact(sid, "hypotheses")["status"] == "awaiting_approval"


def test_plan_is_checked_and_approved_without_a_pipeline(db):
    database, sid = db
    apply_hypothesis_selection(database, sid, ["H1"])
    approved, problems = apply_plan(database, sid, "nonsense", approve=True)
    assert not approved and "no TEST blocks" in problems[-1]
    assert database.get_artifact(sid, "plan")["status"] == "awaiting_approval"

    approved, problems = apply_plan(database, sid, PLAN_TEXT, approve=False)
    assert not approved and problems == []          # checked only, not approved

    approved, problems = apply_plan(database, sid, PLAN_TEXT, approve=True)
    art = database.get_artifact(sid, "plan")
    assert approved and art["approved"] and art["content"]["tests"][0]["problems"] == []
    assert database.get_session(sid)["status"] == "plan_approved"


def test_redoing_a_stage_clears_it_and_everything_built_from_it(db):
    database, sid = db
    apply_hypothesis_selection(database, sid, ["H1"])
    apply_plan(database, sid, PLAN_TEXT, approve=True)
    for stage in ("assembly", "run", "results", "claims", "report", "review"):
        database.save_artifact(sid, stage, {"x": 1}, "passed")
    results = config.session_experiment_dir(sid) / "results"
    results.mkdir(parents=True)
    (results / "H1.T1.json").write_text(json.dumps({"outputs": {}}))

    cleared = invalidate(database, sid, "analysis")

    assert cleared == ["run", "results", "claims", "report", "review"]
    assert not results.exists()                      # old results cannot be mixed with a new run
    assert database.get_artifact(sid, "plan")["status"] == "passed"      # upstream kept
    assert database.get_session(sid)["status"] == "plan_approved"
    assert all(database.get_artifact(sid, s)["status"] == "failed" for s in cleared)


def test_redoing_hypotheses_clears_the_whole_study(db):
    database, sid = db
    apply_hypothesis_selection(database, sid, ["H1"])
    apply_plan(database, sid, PLAN_TEXT, approve=True)
    cleared = invalidate(database, sid, "hypotheses")
    assert cleared == ["hypotheses", "plan"]
    assert database.get_session(sid)["status"] == "data_audited"
    assert set(DOWNSTREAM) == {"hypotheses", "plan", "analysis", "report", "review"}
