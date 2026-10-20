"""
Starting in the middle: what a stage needs, and bringing your own inputs.

2026-09-21: the pipeline was one road from a topic to a report. Someone who
only wants the paper search, or who has their own papers and wants the gap
analysis, or who has a finished study and wants the write-up, had nowhere to
put what they already had.
"""
import json

import pytest

import config
from agents.stages import BY_KEY, blocking, readiness
from memory.importing import ImportError_, import_gap_report, import_papers, import_question, parse_papers
from memory.note_db import NoteDB

CSV = """title,authors,year,abstract
Clean cooking and health,"Kim, Lee",2021,Households switching fuels report fewer symptoms.
Stacking persists after adoption,"Park",2019,Many households keep using solid fuels alongside gas.
"""

BIBTEX = """
@article{kim2021clean,
  title = {Clean cooking and health},
  author = {Kim, A. and Lee, B.},
  journal = {Energy Policy},
  year = {2021},
  abstract = {Households switching fuels report fewer symptoms.}
}
@inproceedings{park2019stacking,
  title = {Stacking persists after adoption},
  author = {Park, C.},
  year = {2019}
}
"""


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    return NoteDB(tmp_path / "t.db")


# --- reading a file someone brings ---------------------------------------------

def test_a_csv_of_papers_is_read():
    papers, problems = parse_papers(CSV, "my-papers.csv")
    assert [p["title"] for p in papers] == ["Clean cooking and health", "Stacking persists after adoption"]
    assert papers[0]["authors"] == "Kim, Lee" and papers[0]["year"] == 2021
    assert problems == []


def test_json_and_bibtex_are_read_too():
    rows = json.dumps([{"Title": "A paper", "Authors": ["Kim", "Lee"], "published": "2020-05-01",
                        "Abstract": "Something."}])
    papers, _ = parse_papers(rows, "papers.json")
    assert papers[0]["title"] == "A paper" and papers[0]["year"] == 2020
    assert papers[0]["authors"] == "Kim, Lee"

    papers, problems = parse_papers(BIBTEX, "library.bib")
    assert [p["title"] for p in papers] == ["Clean cooking and health", "Stacking persists after adoption"]
    assert papers[0]["authors"] == "Kim, A., Lee, B."
    assert any("no abstract" in p for p in problems)       # said, not silently filled in


def test_rows_that_cannot_be_used_are_reported_not_dropped_quietly():
    papers, problems = parse_papers("title,year\n,2020\nA real paper,2021\nA real paper,2022\n", "x.csv")
    assert [p["title"] for p in papers] == ["A real paper"]
    assert any("no title" in p for p in problems)
    assert any("twice" in p for p in problems)


def test_a_file_that_makes_no_sense_is_refused():
    with pytest.raises(ImportError_, match="empty"):
        parse_papers("", "x.csv")
    with pytest.raises(ImportError_, match="no rows"):
        parse_papers("title,year\n", "x.csv")
    with pytest.raises(ImportError_, match="not valid JSON"):
        parse_papers("[{oops}]", "x.json")


# --- putting it into a session ---------------------------------------------------

def test_imported_papers_let_the_session_start_at_the_gap_analysis(db):
    sid = db.create_session("clean cooking")
    result = import_papers(db, sid, CSV, "my-papers.csv")

    assert result["imported"] == 2
    assert len(db.get_papers(sid)) == 2
    assert db.get_session(sid)["status"] == "papers_collected"
    stages = {s["key"]: s for s in readiness(db, sid)}
    assert stages["papers"]["done"] is True
    assert stages["gaps"]["ready"] is True          # the gap stage can run now
    assert stages["review"]["ready"] is True


def test_an_import_is_recorded_so_the_report_can_say_so(db):
    sid = db.create_session("clean cooking")
    import_papers(db, sid, CSV, "my-papers.csv")
    import_gap_report(db, sid, "Gap 1: nobody has looked at stacking after subsidies end. " * 3)

    marks = {d["component"]: d for d in db.get_degradations(sid)}
    assert "imported_papers" in marks and "imported_gap_report" in marks
    assert "not been checked" in marks["imported_gap_report"]["message"]
    assert db.get_session(sid)["gap_report"].startswith("> Imported:")


def test_a_question_written_by_the_user_skips_the_gap_stage(db):
    sid = db.create_session("clean cooking")
    import_papers(db, sid, CSV, "my-papers.csv")
    import_question(db, sid, "Does urban clean fuel use rise faster than rural use?")

    session = db.get_session(sid)
    assert session["status"] == "question_selected"
    art = db.get_artifact(sid, "question")
    assert art["content"]["source"] == "written by the user"
    assert "not checked against the data" in art["content"]["compliance_notes"]
    with pytest.raises(ImportError_):
        import_question(db, sid, "too short")


# --- what can run now ---------------------------------------------------------------

def test_a_new_session_can_only_collect_papers(db):
    sid = db.create_session("clean cooking")
    stages = {s["key"]: s for s in readiness(db, sid)}

    assert stages["papers"]["ready"] is True and stages["papers"]["done"] is False
    assert stages["gaps"]["ready"] is False
    assert stages["gaps"]["missing"][0]["key"] == "papers"
    assert "import a paper list" in stages["gaps"]["missing"][0]["supply"]
    assert stages["report"]["ready"] is False


def test_the_study_stages_need_a_dataset_in_the_brief(db):
    sid = db.create_session("clean cooking", background="no data here")
    import_question(db, sid, "Does urban clean fuel use rise faster than rural use?")
    assert [m["key"] for m in blocking_keys(db, sid, "audit")] == ["dataset"]

    sid2 = db.create_session("clean cooking",
                             background="data: https://example.org/who-gho.zip")
    import_question(db, sid2, "Does urban clean fuel use rise faster than rural use?")
    assert blocking(db, sid2, "audit") == []


def blocking_keys(db, session_id, stage):
    return [m for m in readiness(db, session_id) if m["key"] == stage][0]["missing"]


def test_every_stage_names_a_way_to_supply_what_it_needs(db):
    sid = db.create_session("t")
    for stage in readiness(db, sid):
        for missing in stage["missing"]:
            assert missing["supply"], f"{stage['key']} does not say how to supply {missing['key']}"
    assert set(BY_KEY) == {"papers", "review", "gaps", "audit", "hypotheses",
                           "plan", "analysis", "report", "review_report"}


def test_an_unknown_stage_is_refused(db):
    sid = db.create_session("t")
    with pytest.raises(KeyError):
        blocking(db, sid, "write-my-thesis")


def test_a_stage_whose_output_has_no_record_is_not_called_done_on_an_empty_session(db):
    sid = db.create_session("t")
    stages = {s["key"]: s for s in readiness(db, sid)}
    assert stages["review_report"]["done"] is False
    assert stages["review"]["done"] is False
