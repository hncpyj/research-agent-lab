"""
End-to-end run of the study stages (ui/study_runner.py) on a small synthetic
long-format dataset, with a scripted model and scripted user answers. No
network: dependency installation is stubbed and the analysis runs with this
interpreter.
"""
import json
import sys
import zipfile
from unittest.mock import MagicMock

import numpy as np
import pytest

import config
from memory.note_db import NoteDB
from tools.dataset_schema import DatasetSchema
from ui.study_runner import StudyPipeline

HEADER = ("IndicatorCode,SpatialDimension,SpatialDimensionValueCode,ParentLocationCode,TimeDim,"
          "DisaggregatingDimension1ValueCode,NumericValue")


def _dataset(tmp_path):
    rng = np.random.default_rng(3)
    lines = []
    for u in range(12):
        base = 20 + 5 * u
        for t in range(2000, 2015):
            urb = min(99.0, base + 20 + (1.2 + 0.1 * u) * (t - 2000) + rng.normal(0, 0.3))
            rur = min(99.0, base + (0.6 + 0.05 * u) * (t - 2000) + rng.normal(0, 0.3))
            for code, v in (("AREA_URB", urb), ("AREA_RUR", rur), ("AREA_TOTL", (urb + rur) / 2)):
                lines.append(f"CLEAN,COUNTRY,C{u:02d},AFR,{t},{code},{v:.3f}")
    path = tmp_path / "gho.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("data/CLEAN.csv", HEADER + "\n" + "\n".join(lines) + "\n")
    schema = DatasetSchema(
        url="https://example.org/gho.zip", files=["data/CLEAN.csv"], columns=set(HEADER.split(",")),
        values={"IndicatorCode": {"CLEAN"}, "SpatialDimension": {"COUNTRY"}, "ParentLocationCode": {"AFR"},
                "DisaggregatingDimension1ValueCode": {"AREA_URB", "AREA_RUR", "AREA_TOTL"}},
        meanings={"CLEAN": "Proportion of population using clean fuels (%)", "AFR": "Africa",
                  "AREA_URB": "Urban", "AREA_RUR": "Rural", "AREA_TOTL": "Total"})
    return ("https://example.org/gho.zip", schema, path)


HYPOTHESES_REPLY = """HYPOTHESIS: H1
STATEMENT: Urban clean fuel use rises faster than rural within the same country.
ROW: concept=clean fuel use | variable=CLEAN | expect=rising
ROW: concept=urban versus rural | variable=DisaggregatingDimension1ValueCode:AREA_URB,AREA_RUR | expect=urban faster
CANNOT_TEST: the role of fuel subsidy policies
HYPOTHESIS: H2
STATEMENT: Stricter energy policy raises clean fuel use.
ROW: concept=energy policy stringency | variable=CLEAN | expect=higher
CANNOT_TEST: none
"""

PLAN_REPLY = """TEST: H1.T1
COMPARES: urban minus rural yearly trend within countries
BLOCK: paired_difference
PARAMS: indicator=CLEAN, pair=urban,rural, stat=slope, bootstrap=200
SUPPORT_IF: mean > 0 AND ci_low > 0
REJECT_IF: ci_high < 0
THREATS: synthetic data
"""

CLAIMS_REPLY = "CLAIM: C1\nTEXT: Across {n} countries urban use rose faster than rural.\nEVIDENCE: R1\n"


class _Embed:
    def embed(self, text):
        return [0.0, 1.0] if "policy" in text.lower() else [1.0, 0.2]


class _Runner:
    def __init__(self, session_id, answers):
        self.session_id = session_id
        self.events = []
        self.answers = answers
        self._stop_flag = MagicMock(is_set=lambda: False)

    def emit(self, kind, data=None):
        self.events.append((kind, data))

    def wait_for_input(self, step, message):
        return self.answers[step].pop(0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "RUNNER_PYTHON", sys.executable)
    import agents.experiment_runner as er
    monkeypatch.setattr(er.ExperimentRunnerAgent, "_run_phase_install",
                        lambda self, sid, hid, folder: self._ndb.finish_experiment_run(
                            self._ndb.create_experiment_run(sid, hid, "install"), "success"))
    monkeypatch.setattr(StudyPipeline, "_embedder", lambda self: _Embed())
    db = NoteDB(tmp_path / "t.db")
    sid = db.create_session("clean cooking", background="data at https://example.org/gho.zip")
    db.update_session(sid, research_question="Does urban clean fuel use rise faster than rural?",
                      gap_report="- gap [1]")
    db.save_paper(sid, {"arxiv_id": "p1", "title": "Paper one", "authors": "A", "year": 2020, "abstract": "x"})
    return db, sid, _dataset(tmp_path)


def _api(replies):
    api = MagicMock()
    api.generate.side_effect = replies
    return api


def test_full_study_runs_through_the_gates_and_writes_a_checked_report(env):
    db, sid, declared = env
    first_plan = PLAN_REPLY.replace("stat=slope", "stat=velocity")          # invalid, fixed by the user below
    api = _api([HYPOTHESES_REPLY, first_plan, first_plan,
                CLAIMS_REPLY.format(n=12),
                "Abstract: urban rose faster; the policy question could not be tested.",
                "Discussion.", "Conclusion: the policy part could not be tested.",
                "ISSUE: none"])
    runner = _Runner(sid, {
        "hypothesis_selection": [["H2"], ["H1"]],                             # H2 is untestable: rejected first
        "plan_approval": [{"text": first_plan, "approve": True},                # has problems: cannot approve
                          {"text": PLAN_REPLY, "approve": True}],
    })

    assert StudyPipeline(runner, db, api, declared).run() is True

    arts = {a["stage"]: a for a in db.list_artifacts(sid)}
    hyps = {h["id"]: h for h in arts["hypotheses"]["content"]["hypotheses"]}
    assert hyps["H1"]["testable"] and not hyps["H2"]["testable"]
    assert arts["hypotheses"]["content"]["selected"] == ["H1"] and arts["hypotheses"]["approved"]
    assert arts["plan"]["approved"] and arts["plan"]["content"]["tests"][0]["problems"] == []
    assert arts["run"]["status"] == "passed"

    rows = {r["id"]: r for r in arts["results"]["content"]["rows"]}
    assert rows["R1"]["verdict"] == "supported"
    assert rows["R1"]["values"]["n_units"] == 12
    assert {r["verdict"] for r in rows.values()} >= {"untestable"}

    assert [c["id"] for c in arts["claims"]["content"]["accepted"]] == ["C1"]
    report = json.loads(db.get_session(sid)["report"])
    assert "Stricter energy policy" in report["limitations"]
    assert "fuel subsidy policies" in report["limitations"]
    assert (config.BASE_DIR / "data" / "reports" / sid / "report.json").exists()
    assert db.get_session(sid)["status"] == "reviewed"
    notebook = (config.session_experiment_dir(sid) / "notebook.jsonl").read_text().splitlines()
    assert json.loads(notebook[-1])["exit_code"] == 0
    kinds = [k for k, _ in runner.events]
    assert kinds.index("hypothesis_candidates") < kinds.index("analysis_plan") < kinds.index("results_table")


def test_resume_reuses_approved_stages_and_the_analysis_run(env):
    db, sid, declared = env
    replies = [HYPOTHESES_REPLY, PLAN_REPLY, CLAIMS_REPLY.format(n=12),
               "A: the policy part could not be tested.", "D.", "C: it could not be tested.", "ISSUE: none"]
    answers = {"hypothesis_selection": [["H1"]], "plan_approval": [{"text": PLAN_REPLY, "approve": True}]}
    StudyPipeline(_Runner(sid, answers), db, _api(replies), declared).run()

    api = _api([])                       # a second run must not call the model or wait for the user
    runner = _Runner(sid, {"hypothesis_selection": [], "plan_approval": []})
    assert StudyPipeline(runner, db, api, declared).run() is True
    api.generate.assert_not_called()


def test_no_testable_hypothesis_blocks_before_any_analysis(env):
    db, sid, declared = env
    only_policy = HYPOTHESES_REPLY.split("HYPOTHESIS: H2")[1]
    api = _api(["HYPOTHESIS: H2" + only_policy])
    runner = _Runner(sid, {})
    assert StudyPipeline(runner, db, api, declared).run() is False
    assert db.get_artifact(sid, "hypotheses")["status"] == "blocked"
    assert db.get_artifact(sid, "plan") is None
    assert any(k == "study_blocked" for k, _ in runner.events)


def test_every_status_the_study_sets_is_known_to_the_resume_logic():
    # 2026-09-14: 'data_audited' was missing from the runner's order, and a resume
    # re-ran paper collection and gap analysis (external requests included).
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    set_by_study = set(re.findall(r'status="([a-z_]+)"', (root / "ui" / "study_runner.py").read_text(encoding="utf-8")))
    runner_src = (root / "ui" / "runner.py").read_text(encoding="utf-8")
    order = re.search(r"STATUS_ORDER = \[(.*?)\]", runner_src, re.S).group(1)
    known = set(re.findall(r'"([a-z_]+)"', order))
    assert set_by_study and set_by_study <= known, set_by_study - known
    ui = (root / "ui" / "static" / "index.html").read_text(encoding="utf-8")
    assert all(f"{s}:" in ui for s in set_by_study)
