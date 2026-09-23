"""
Projects, one record per paper, and where a result came from.

Sessions were a flat list: related work could not be grouped, the same paper
existed as one row per session, and the only way to answer "what is this report
built on?" was to read the whole session.

These pin what a project may claim about itself, what counts as the same paper,
and that the chain behind a report is read from what was stored rather than
assumed from the shape of the pipeline.
"""
import pytest
from fastapi.testclient import TestClient

import config
from memory import accounts, paper_index, projects, provenance
from memory.accounts import User
from memory.note_db import NoteDB


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    return NoteDB()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    monkeypatch.setattr(config, "UI_TOKEN", "")
    monkeypatch.setattr(config, "ALLOW_SIGNUP", True)
    import ui.app as ui_app
    ui_app._runners.clear()
    ui_app._LOGIN_ATTEMPTS.clear()
    return TestClient(ui_app.app)


def _free_user(user_id="u1"):
    return User(user_id=user_id, email="a@example.com", role="member", plan="free",
                created_at="2026-09-01T00:00:00+00:00")


# --- projects ----------------------------------------------------------------------

def test_a_project_holds_sessions_and_says_what_it_amounts_to(db):
    project = projects.create("Clean cooking", owner_id="u1")
    first = db.create_session("adoption", owner_id="u1", project_id=project["project_id"])
    second = db.create_session("fuel stacking", owner_id="u1")
    projects.assign(second, project["project_id"])
    db.save_paper(first, {"arxiv_id": "2101.00001", "title": "Stoves and smoke"})
    db.save_paper(second, {"arxiv_id": "2101.00001", "title": "Stoves and smoke"})
    db.save_paper(second, {"doi": "10.1000/xyz", "title": "Another one"})

    summary = projects.summary(project["project_id"])
    assert summary["sessions"] == 2
    assert summary["papers"] == 2            # the shared paper counts once
    assert summary["name"] == "Clean cooking" and summary["archived"] is False


def test_a_session_can_be_taken_out_of_a_project(db):
    project = projects.create("P", owner_id="u1")
    sid = db.create_session("t", owner_id="u1", project_id=project["project_id"])
    projects.assign(sid, "")
    assert projects.sessions_of(project["project_id"]) == []
    assert db.get_session(sid)["project_id"] == ""


def test_the_free_plan_keeps_three_projects_open(db):
    user = _free_user()
    for i in range(3):
        projects.create(f"P{i}", owner_id=user.user_id, user=user)

    with pytest.raises(projects.ProjectLimit) as refused:
        projects.create("one too many", owner_id=user.user_id, user=user)
    assert refused.value.limit == 3
    assert "Archive one" in str(refused.value)


def test_archiving_frees_a_place_and_keeps_the_research(db):
    user = _free_user()
    made = [projects.create(f"P{i}", owner_id=user.user_id, user=user) for i in range(3)]
    sid = db.create_session("t", owner_id=user.user_id, project_id=made[0]["project_id"])

    projects.archive(made[0]["project_id"])
    projects.create("room for another", owner_id=user.user_id, user=user)

    assert len(projects.list_projects(user.user_id)) == 3
    assert len(projects.list_projects(user.user_id, include_archived=True)) == 4
    assert [s["session_id"] for s in projects.sessions_of(made[0]["project_id"])] == [sid]


def test_bringing_an_archived_project_back_is_refused_when_full(db):
    user = _free_user()
    first = projects.create("P0", owner_id=user.user_id, user=user)
    projects.archive(first["project_id"])
    for i in range(3):
        projects.create(f"Q{i}", owner_id=user.user_id, user=user)

    with pytest.raises(projects.ProjectLimit):
        projects.archive(first["project_id"], archived=False, user=user)


def test_running_it_yourself_is_not_limited(db):
    for i in range(6):
        projects.create(f"P{i}")                  # no user: own machine
    assert len(projects.list_projects("")) == 6


def test_a_project_needs_a_name(db):
    with pytest.raises(projects.ProjectError, match="needs a name"):
        projects.create("   ")


# --- one record per paper -------------------------------------------------------------

@pytest.mark.parametrize("first, second", [
    ({"doi": "10.1000/ABC"}, {"doi": "https://doi.org/10.1000/abc"}),
    ({"arxiv_id": "2110.05038v2"}, {"arxiv_id": "2110.05038"}),
    ({"arxiv_id": "https://arxiv.org/abs/2110.05038"}, {"arxiv_id": "2110.05038v4"}),
    ({"title": "Recurrent Model-Free RL Can Be a Strong Baseline"},
     {"title": "recurrent model-free rl can be a strong baseline!"}),
])
def test_the_same_paper_is_recognised_however_it_is_written(first, second):
    assert paper_index.canonical_id(first) == paper_index.canonical_id(second)


@pytest.mark.parametrize("paper", [
    {"title": "Short"},                 # too short to be a title
    {"title": "", "arxiv_id": ""},
    {},
])
def test_a_paper_with_nothing_to_identify_it_is_left_alone(paper):
    assert paper_index.canonical_id(paper) is None


def test_two_different_papers_are_not_merged():
    a = {"title": "Transformers for reinforcement learning"}
    b = {"title": "Transformers for natural language"}
    assert paper_index.canonical_id(a) != paper_index.canonical_id(b)


def test_a_dois_paper_and_its_preprint_stay_one_record_by_doi(db):
    sid = db.create_session("t")
    db.save_paper(sid, {"doi": "10.1000/xyz", "arxiv_id": "2101.1", "title": "A"})
    db.save_paper(sid, {"doi": "10.1000/xyz", "arxiv_id": "2101.1v3", "title": "A, revised"})
    assert paper_index.count_for([sid]) == 1


def test_the_library_says_which_sessions_read_each_paper(db):
    one = db.create_session("first")
    two = db.create_session("second")
    for sid in (one, two):
        db.save_paper(sid, {"arxiv_id": "2110.05038", "title": "Shared paper", "year": 2021})
    db.save_paper(two, {"arxiv_id": "2201.00001", "title": "Only in the second"})

    library = paper_index.library([one, two])
    assert [p["title"] for p in library] == ["Shared paper", "Only in the second"]
    assert library[0]["sessions"] == 2
    assert sorted(library[0]["session_ids"]) == sorted([one, two])


def test_papers_saved_before_the_index_existed_are_filed_on_first_read(db):
    """The index has to repair itself, or every earlier session reads as empty."""
    sid = db.create_session("t")
    db.save_paper(sid, {"arxiv_id": "2110.05038", "title": "An older paper"})
    conn = paper_index._connect()
    conn.execute("DELETE FROM paper_occurrences")
    conn.execute("DELETE FROM canonical_papers")
    conn.commit(); conn.close()

    assert paper_index.count_for([sid]) == 1


def test_sessions_that_read_the_same_papers_are_linked(db):
    one, two, three = (db.create_session(t) for t in ("a", "b", "c"))
    for sid in (one, two):
        db.save_paper(sid, {"arxiv_id": "2110.05038", "title": "Shared"})
    db.save_paper(three, {"arxiv_id": "2201.00002", "title": "Its own"})

    links = paper_index.sessions_sharing([one, two, three])
    assert len(links) == 1 and links[0]["shared"] == 1
    assert {links[0]["left_id"], links[0]["right_id"]} == {one, two}


# --- where a result came from ----------------------------------------------------------

def _a_finished_study(db):
    sid = db.create_session("energy transition", background="b", goals="g")
    db.save_paper(sid, {"arxiv_id": "2110.05038", "title": "A paper", "source": "arxiv"})
    db.update_session(sid, gap_report="a gap", research_question="does it fall?")
    db.save_artifact(sid, "data_audit", {"indicators": 3}, "passed")
    db.save_artifact(sid, "hypotheses", {"hypotheses": [{"id": "H1"}]}, "passed")
    db.save_artifact(sid, "plan", {"tests": ["t1"]}, "passed")
    results = db.save_artifact(sid, "results", {"rows": [{"id": "R1"}, {"id": "R2"}]}, "passed")
    table = db.get_artifact(sid, "results")
    db.save_artifact(sid, "claims", {"claims": [{"id": "C1"}],
                                     "results_hash": table["content_hash"]}, "passed")
    db.save_artifact(sid, "report", {"title": "T", "results_hash": table["content_hash"]}, "passed")
    return sid, results


def test_the_chain_behind_a_report_is_read_from_what_was_stored(db):
    sid, _ = _a_finished_study(db)

    graph = provenance.graph(db, sid)
    steps = {n["id"] for n in graph["nodes"]}
    assert {"brief", "papers", "gap_report", "question", "hypotheses",
            "plan", "results", "claims", "report"} <= steps
    assert {"from": "results", "to": "claims"} in graph["edges"]
    shown = [n["id"] for n in graph["nodes"]]
    assert shown.index("results") < shown.index("claims") < shown.index("report")
    assert {"from": "claims", "to": "report"} in graph["edges"]
    assert graph["complete"] is True


def test_a_step_that_never_ran_is_absent_not_empty(db):
    sid = db.create_session("only a brief")

    graph = provenance.graph(db, sid)
    assert [n["id"] for n in graph["nodes"]] == ["brief"]
    assert graph["edges"] == [] and graph["complete"] is False


def test_each_step_carries_what_it_actually_holds(db):
    sid, _ = _a_finished_study(db)
    nodes = {n["id"]: n for n in provenance.graph(db, sid)["nodes"]}

    assert nodes["papers"]["count"] == 1
    assert nodes["papers"]["detail"]["by_source"] == {"arxiv": 1}
    assert nodes["results"]["detail"]["rows"] == 2
    assert nodes["claims"]["detail"]["claims"] == 1


def test_a_rebuilt_step_makes_what_was_built_on_it_stale(db):
    """The hashes exist to be checked: a report built on an older table must say so."""
    sid, _ = _a_finished_study(db)
    db.save_artifact(sid, "results", {"rows": [{"id": "R1"}, {"id": "R2"}, {"id": "R3"}]}, "passed")

    nodes = {n["id"]: n for n in provenance.graph(db, sid)["nodes"]}
    assert nodes["claims"].get("stale") is True
    assert "has since been rebuilt" in nodes["claims"]["degradations"][0]["message"]


def test_what_went_wrong_is_shown_at_the_step_it_happened(db):
    sid, _ = _a_finished_study(db)
    db.save_degradation(sid, 2, "gap_validation", "critical", "a claimed gap was already addressed")

    nodes = {n["id"]: n for n in provenance.graph(db, sid)["nodes"]}
    assert nodes["gap_report"]["degradations"][0]["severity"] == "critical"


def test_how_many_times_a_stage_was_rebuilt_is_visible(db):
    sid, _ = _a_finished_study(db)
    db.save_artifact(sid, "plan", {"tests": ["t1", "t2"]}, "passed")

    nodes = {n["id"]: n for n in provenance.graph(db, sid)["nodes"]}
    assert nodes["plan"]["versions"] == 2


def test_a_project_graph_links_sessions_by_the_papers_they_share(db):
    project = projects.create("P")
    one = db.create_session("first", project_id=project["project_id"])
    two = db.create_session("second", project_id=project["project_id"])
    for sid in (one, two):
        db.save_paper(sid, {"arxiv_id": "2110.05038", "title": "Shared"})

    graph = provenance.project_graph(db, projects.sessions_of(project["project_id"]))
    assert {n["id"] for n in graph["nodes"]} == {one, two}
    assert graph["edges"][0]["shared_papers"] == 1
    assert graph["papers"] == 1


# --- over HTTP ---------------------------------------------------------------------

def test_projects_can_be_made_filed_and_read_from_the_page(client):
    made = client.post("/api/projects", json={"name": "Clean cooking"}).json()
    session_id = client.post("/api/sessions", json={"topic": "adoption", "autostart": False,
                                                    "project_id": made["project_id"]}).json()["session_id"]

    listed = client.get("/api/projects").json()
    assert [p["name"] for p in listed["projects"]] == ["Clean cooking"]
    assert listed["projects"][0]["sessions"] == 1

    client.post(f"/api/sessions/{session_id}/project", json={"project_id": ""})
    assert client.get("/api/projects").json()["projects"][0]["sessions"] == 0
    assert client.get("/api/projects").json()["unfiled"] == 1


def test_the_page_can_read_the_chain_behind_a_session(client):
    session_id = client.post("/api/sessions", json={"topic": "t", "autostart": False}).json()["session_id"]
    graph = client.get(f"/api/sessions/{session_id}/provenance").json()
    assert [n["id"] for n in graph["nodes"]] == ["brief"]


def test_one_account_cannot_see_another_accounts_project(client):
    client.post("/api/auth/signup", json={"email": "owner@example.com", "password": "a-good-password"})
    mine = client.post("/api/projects", json={"name": "Mine"}).json()
    client.post("/api/auth/logout")

    client.post("/api/auth/signup", json={"email": "other@example.com", "password": "a-good-password"})
    assert client.get("/api/projects").json()["projects"] == []
    assert client.get(f"/api/projects/{mine['project_id']}/papers").status_code == 404
    assert client.patch(f"/api/projects/{mine['project_id']}",
                        json={"name": "Renamed"}).status_code == 404


def test_the_limit_is_explained_rather_than_just_refused(client):
    client.post("/api/auth/signup", json={"email": "owner@example.com", "password": "a-good-password"})
    accounts.set_plan(accounts.verify_password("owner@example.com", "a-good-password").user_id, "free")
    for i in range(3):
        assert client.post("/api/projects", json={"name": f"P{i}"}).status_code == 200

    refused = client.post("/api/projects", json={"name": "one too many"})
    assert refused.status_code == 409
    assert "Archive one" in refused.json()["detail"]

    project_id = client.get("/api/projects").json()["projects"][0]["project_id"]
    client.patch(f"/api/projects/{project_id}", json={"archived": True})
    assert client.post("/api/projects", json={"name": "now there is room"}).status_code == 200
