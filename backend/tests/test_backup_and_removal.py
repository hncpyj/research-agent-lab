"""
Backups, export and session removal (memory/backup.py).

2026-09-20 product audit: every session lived in one SQLite file with no
backup, no export and no way to remove a session.
"""
import json

import pytest

import config
from memory import backup as backup_mod
from memory.backup import backup_db, backup_if_stale, export_session, list_backups, remove_session
from memory.note_db import NoteDB


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "DB_DIR", tmp_path / "data" / "db")
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    (tmp_path / "data" / "db").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "data" / "db" / "research.db")

    db = NoteDB(config.SQLITE_PATH)
    sid = db.create_session("clean cooking", background="b", goals="g", constraints="c")
    db.save_paper(sid, {"arxiv_id": "p1", "title": "Paper one", "authors": "A", "year": 2020, "abstract": "x"})
    db.save_artifact(sid, "results", {"rows": [{"id": "R1"}]}, "passed")
    db.save_degradation(sid, 1, "canon_seeding", "critical", "blocked")
    folder = config.session_experiment_dir(sid)
    (folder / "results").mkdir(parents=True)
    (folder / "results" / "R1.json").write_text("{}")
    (folder / "notebook.jsonl").write_text(json.dumps({"phase": "analysis", "exit_code": 0}) + "\n")
    reports = tmp_path / "data" / "reports" / sid
    reports.mkdir(parents=True)
    (reports / "report.json").write_text(json.dumps({"title": "T"}), encoding="utf-8")
    return db, sid


def test_a_backup_is_a_usable_copy(project):
    db, sid = project
    path = backup_db("test")
    assert path.exists() and path.stat().st_size > 0
    restored = NoteDB(path)
    assert restored.get_session(sid)["topic"] == "clean cooking"
    assert [p["title"] for p in restored.get_papers(sid)] == ["Paper one"]


def test_only_the_last_backups_are_kept(project):
    for i in range(4):
        backup_db(f"test{i}", keep=2)
    assert len(list_backups()) == 2


def test_a_daily_backup_is_made_once(project):
    assert backup_if_stale() is not None
    assert backup_if_stale() is None          # one already exists for today


def test_export_holds_everything_needed_to_rebuild_the_session(project):
    db, sid = project
    bundle = export_session(sid)
    assert bundle["tables"]["research_sessions"][0]["topic"] == "clean cooking"
    assert bundle["tables"]["papers"][0]["title"] == "Paper one"
    assert bundle["tables"]["research_artifacts"][0]["stage"] == "results"
    assert bundle["tables"]["degradations"][0]["component"] == "canon_seeding"
    assert bundle["report"] == {"title": "T"}
    assert bundle["experiment_files"] == ["notebook.jsonl", "results/R1.json"]
    assert json.loads(bundle["notebook"][0])["exit_code"] == 0
    with pytest.raises(KeyError):
        export_session("no-such-session")


def test_removal_keeps_a_bundle_and_the_folders(project):
    db, sid = project
    result = remove_session(sid)

    assert db.get_session(sid) is None and db.get_papers(sid) == []
    assert db.list_artifacts(sid) == [] and db.get_degradations(sid) == []
    assert not config.session_experiment_dir(sid).exists()

    kept = backup_mod.removed_dir() / sid
    saved = json.loads((kept / "session.json").read_text(encoding="utf-8"))
    assert saved["tables"]["research_sessions"][0]["topic"] == "clean cooking"
    assert (kept / "experiments" / "results" / "R1.json").exists()
    assert (kept / "reports" / "report.json").exists()
    assert result["rows_removed"]["papers"] == 1
    assert list_backups()                      # the database was backed up first
