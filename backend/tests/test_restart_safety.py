"""
What happens to a run when the server stops (memory/runs.py).

A run lived only in a thread inside the web server. Stopping the server --
a deploy, a crash, a closed laptop -- left the session frozen mid-phase with
nothing written down: the page still offered to watch a run that no longer
existed, and the place that run held in the plan's allowance was never given
back, so a free account could end up unable to start anything ever again.

These pin the three things that must now be true after a restart: the place is
returned, the session is told, and nothing restarts on its own.
"""
import os

import pytest

import config
from memory import accounts, quota, runs
from memory.note_db import NoteDB


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    return tmp_path / "t.db"


def _a_session(topic="clean cooking"):
    store = NoteDB()
    return store, store.create_session(topic, background="b", goals="g", constraints="c")


def _left_behind_by_a_dead_server(session_id, run_id="", stage="full", pid=0):
    """A row as an earlier process would have written it, then died."""
    runs.begin(session_id, run_id, stage)
    conn = runs._connect()
    conn.execute("UPDATE active_runs SET boot_id = 'a-server-that-is-gone', pid = ?, host = ? "
                 "WHERE session_id = ?", (pid or 999_999, runs.HOST, session_id))
    conn.commit()
    conn.close()


# --- the leftovers ------------------------------------------------------------------

def test_a_run_from_a_server_that_is_gone_is_marked_interrupted(db):
    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid)

    recovered = runs.recover()

    assert [r["session_id"] for r in recovered] == [sid]
    assert runs.interrupted(sid)["note"] == runs.INTERRUPTED_NOTE


def test_the_session_is_told_why_it_stopped(db):
    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid)

    runs.recover()

    reported = store.get_degradations(sid)
    assert [d["component"] for d in reported] == ["run_interrupted"]
    assert "resume the session" in reported[0]["message"]
    assert reported[0]["severity"] == "critical"


def test_the_allowance_place_is_given_back_and_not_charged(db):
    """The whole reason this exists: a restart must not cost the user a run."""
    user = accounts.create_user("owner@example.com", "Good!Password123")
    store, sid = _a_session()
    run_id = quota.reserve(user, session_id=sid, stage="full")
    quota.start(run_id, sid)
    _left_behind_by_a_dead_server(sid, run_id)

    assert quota.allowance(user).running == 1          # held before recovery
    runs.recover()

    left = quota.allowance(user)
    assert left.running == 0 and left.reserved == 0
    assert left.used == 0                              # our fault, not their run
    assert quota.history(user)[0]["outcome"] == "failed_system"
    assert "server stopped" in quota.history(user)[0]["reason"]


def test_a_recovered_run_is_not_started_again(db, monkeypatch):
    """Research costs money and stops at gates; a reboot may not start one."""
    started = []
    import ui.runner as runner_module
    monkeypatch.setattr(runner_module.SessionRunner, "start",
                        lambda self: started.append(self.session_id))

    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid)
    runs.recover()

    assert started == []


def test_recovering_twice_reports_it_once(db):
    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid)

    assert len(runs.recover()) == 1
    assert runs.recover() == []
    assert len(store.get_degradations(sid)) == 1


# --- what must not be touched --------------------------------------------------------

def test_a_run_this_server_is_working_on_is_left_alone(db):
    store, sid = _a_session()
    runs.begin(sid, "", "full")                        # ours: same boot id

    assert runs.recover() == []
    assert runs.get(sid)["state"] == runs.RUNNING


def test_another_live_server_keeps_its_runs(db, monkeypatch):
    """Two servers on one database: the one starting up must not end the other's work."""
    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid, pid=os.getpid())   # a pid that is alive

    assert runs.recover() == []
    assert runs.get(sid)["state"] == runs.RUNNING


def test_a_silent_run_is_eventually_given_up_on(db, monkeypatch):
    """A process we cannot check must not hold a place for ever."""
    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid, pid=os.getpid())
    conn = runs._connect()
    conn.execute("UPDATE active_runs SET heartbeat_at = '2020-01-01T00:00:00+00:00'")
    conn.commit(); conn.close()

    assert [r["session_id"] for r in runs.recover()] == [sid]


def test_a_run_that_ended_properly_leaves_nothing_behind(db):
    store, sid = _a_session()
    runs.begin(sid, "", "full")
    runs.finish(sid)

    assert runs.get(sid) is None
    assert runs.recover() == []


def test_a_missing_session_is_not_a_crash(db):
    _left_behind_by_a_dead_server("a-session-that-was-deleted")
    assert len(runs.recover()) == 1                    # settled and cleared, nothing raised


# --- the runner writes and clears its own row ----------------------------------------

def test_the_runner_records_that_it_is_working_and_clears_it_at_the_end(db, monkeypatch):
    import ui.runner as runner_module

    store, sid = _a_session()
    runner = runner_module.SessionRunner(session_id=sid, topic="t")
    seen = {}
    monkeypatch.setattr(runner, "_run", lambda: seen.update(row=runs.get(sid)))
    runner.start()
    runner._thread.join(timeout=10)

    assert seen["row"]["state"] == runs.RUNNING        # written before the work
    assert seen["row"]["boot_id"] == runs.BOOT_ID
    assert runs.get(sid) is None                       # and cleared afterwards


def test_a_crashed_run_clears_its_row_too(db, monkeypatch):
    import ui.runner as runner_module

    store, sid = _a_session()
    runner = runner_module.SessionRunner(session_id=sid, topic="t")
    runner.start()
    runner._thread.join(timeout=10)
    monkeypatch.setattr(runner, "_run", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    runner._safe_run()

    assert runs.get(sid) is None


def test_working_keeps_the_row_fresh(db):
    import ui.runner as runner_module

    store, sid = _a_session()
    runner = runner_module.SessionRunner(session_id=sid, topic="t")
    runs.begin(sid, "", "full")
    conn = runs._connect()
    conn.execute("UPDATE active_runs SET heartbeat_at = '2020-01-01T00:00:00+00:00'")
    conn.commit(); conn.close()

    runner.emit("log", {"message": "still here"})
    assert runs.get(sid)["heartbeat_at"] > "2025"


# --- what the page is told -----------------------------------------------------------

def test_the_page_is_told_which_sessions_stopped_part_way(db, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "UI_TOKEN", "")
    import ui.app as ui_app
    ui_app._runners.clear()
    client = TestClient(ui_app.app)

    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid)
    runs.recover()

    listed = client.get("/api/sessions").json()["sessions"]
    assert [s["interrupted"] for s in listed if s["session_id"] == sid] == [True]

    status = client.get(f"/api/sessions/{sid}/status").json()
    assert status["running"] is False
    assert "resume the session" in status["interrupted"]["note"]


def test_starting_the_session_again_clears_the_marker(db, monkeypatch):
    store, sid = _a_session()
    _left_behind_by_a_dead_server(sid)
    runs.recover()
    assert runs.interrupted(sid)

    import ui.runner as runner_module
    runner = runner_module.SessionRunner(session_id=sid, topic="t")
    monkeypatch.setattr(runner, "_run", lambda: None)
    runner.start()
    runner._thread.join(timeout=10)

    assert runs.interrupted(sid) is None
