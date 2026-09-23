"""
What a plan allows, and what a failed run costs the person who started it.

Two things this has to get right: a run is claimed before it starts (so two
clicks at once cannot both take the last one), and a run that failed because of
the server does not come out of the user's allowance.
"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

import config
from memory import plans, quota
from memory.accounts import User


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path / "t.db"


def _user(plan="free", user_id="u1"):
    return User(user_id=user_id, email=f"{user_id}@example.com", role="member",
                plan=plan, created_at="2026-09-01T00:00:00+00:00")


# --- plans ---------------------------------------------------------------------

def test_the_two_plans_say_what_the_pricing_page_says():
    free, researcher = plans.describe()
    assert free["price_gbp_month"] == 0.0 and researcher["price_gbp_month"] == 9.0
    assert free["hosted_runs_per_period"] == 10 and free["concurrent_runs"] == 1
    assert free["active_projects"] == 3 and free["managed_credit_gbp_per_period"] == 0.0
    assert researcher["hosted_runs_per_period"] is None     # unlimited in count
    assert researcher["concurrent_runs"] == 2               # but not in rate
    assert researcher["managed_credit_gbp_per_period"] == 9.0
    assert free["local_runner"] is True and researcher["cross_session_memory"] is True


def test_running_it_yourself_is_not_limited_by_a_plan():
    assert plans.plan_for(None).key == "self_hosted"
    assert plans.allows(None, "hosted_runs_per_period") is None
    assert plans.allows(None, "research_graph") is True


def test_an_unknown_entitlement_is_a_mistake_not_a_silent_false():
    with pytest.raises(KeyError, match="unknown entitlement"):
        plans.allows(_user(), "unlimited_everything")


# --- the allowance ----------------------------------------------------------------

def test_the_free_allowance_is_ten_runs_a_month(db):
    user = _user()
    for _ in range(10):
        run = quota.reserve(user, db_path=db)
        quota.settle(run, quota.COMPLETED, db_path=db)

    left = quota.allowance(user, db_path=db)
    assert left.used == 10 and left.remaining == 0
    with pytest.raises(quota.QuotaExceeded) as refused:
        quota.reserve(user, db_path=db)
    assert refused.value.reason == "allowance"
    assert "resets at the start of next month" in str(refused.value)


def test_a_researcher_is_not_capped_by_count(db):
    user = _user(plan="researcher", user_id="r1")
    for _ in range(25):
        run = quota.reserve(user, db_path=db)
        quota.settle(run, quota.COMPLETED, db_path=db)
    assert quota.allowance(user, db_path=db).remaining is None


def test_concurrency_is_limited_even_when_the_count_is_not(db):
    user = _user(plan="researcher", user_id="r2")
    first, second = quota.reserve(user, db_path=db), quota.reserve(user, db_path=db)
    quota.start(first, db_path=db)

    with pytest.raises(quota.QuotaExceeded) as refused:
        quota.reserve(user, db_path=db)
    assert refused.value.reason == "concurrency" and "2 research runs at a time" in str(refused.value)

    quota.settle(second, quota.CANCELLED, db_path=db)
    assert quota.reserve(user, db_path=db)          # a place freed up


def test_two_requests_at_once_cannot_both_take_the_last_place(db):
    """The check and the claim are one transaction, so a double click cannot pass twice."""
    user = _user(user_id="racer")
    for _ in range(9):
        quota.settle(quota.reserve(user, db_path=db), quota.COMPLETED, db_path=db)

    def attempt(_):
        try:
            return quota.reserve(user, db_path=db)
        except quota.QuotaExceeded:
            return None
        except sqlite3.OperationalError:            # lock contention, not a free pass
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert len([r for r in results if r]) == 1
    assert quota.allowance(user, db_path=db).remaining == 0


# --- what a failure costs -----------------------------------------------------------

def test_our_own_failure_does_not_come_out_of_the_allowance(db):
    user = _user(user_id="unlucky")
    for outcome in (quota.FAILED_SYSTEM, quota.FAILED_PROVIDER, quota.CANCELLED):
        run = quota.reserve(user, db_path=db)
        counted = quota.settle(run, outcome, reason="for the record", db_path=db)
        assert counted is False
    assert quota.allowance(user, db_path=db).used == 0

    run = quota.reserve(user, db_path=db)
    assert quota.settle(run, quota.FAILED_USER, db_path=db) is True   # a bad brief is still a run
    assert quota.allowance(user, db_path=db).used == 1


def test_settling_twice_does_not_count_twice(db):
    user = _user(user_id="twice")
    run = quota.reserve(user, db_path=db)
    assert quota.settle(run, quota.COMPLETED, db_path=db) is True
    assert quota.settle(run, quota.COMPLETED, db_path=db) is False
    assert quota.allowance(user, db_path=db).used == 1


def test_every_run_leaves_a_record_that_can_be_checked(db):
    user = _user(user_id="audit")
    run = quota.reserve(user, session_id="s1", stage="papers", db_path=db)
    quota.start(run, db_path=db)
    quota.settle(run, quota.FAILED_SYSTEM, reason="the server restarted", db_path=db)

    entry = quota.history(user, db_path=db)[0]
    assert entry["session_id"] == "s1" and entry["stage"] == "papers"
    assert entry["outcome"] == "failed_system" and entry["counted"] == 0
    assert entry["reason"] == "the server restarted" and entry["settled_at"]


def test_the_period_is_stored_not_guessed(db):
    user = _user(user_id="period")
    left = quota.allowance(user, db_path=db)
    assert left.period_start.endswith("-01T00:00:00+00:00")
    assert left.period_end > left.period_start
    assert left.plan == "free"


# --- the runner settles its own place ------------------------------------------------

def test_a_crashed_run_is_recorded_as_our_fault(db, monkeypatch):
    """A pipeline that raises must not take a run out of the user's allowance."""
    import ui.runner as runner_module

    user = _user(user_id="crash")
    run_id = quota.reserve(user, db_path=db)
    monkeypatch.setattr(config, "SQLITE_PATH", db)

    runner = runner_module.SessionRunner(session_id="s1", topic="t")
    runner.run_id = run_id
    monkeypatch.setattr(runner, "_run", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    runner._safe_run()

    entry = quota.history(user, db_path=db)[0]
    assert entry["outcome"] == "failed_system" and entry["counted"] == 0
    assert "boom" in entry["reason"]
    assert quota.allowance(user, db_path=db).used == 0


def test_a_run_the_user_stopped_is_not_charged(db, monkeypatch):
    import ui.runner as runner_module

    user = _user(user_id="stopper")
    run_id = quota.reserve(user, db_path=db)
    monkeypatch.setattr(config, "SQLITE_PATH", db)

    runner = runner_module.SessionRunner(session_id="s1", topic="t")
    runner.run_id = run_id
    monkeypatch.setattr(runner, "_run", lambda: runner._stop_flag.set())
    runner._safe_run()

    assert quota.history(user, db_path=db)[0]["outcome"] == "cancelled"
    assert quota.allowance(user, db_path=db).used == 0


def test_a_finished_run_counts_once(db, monkeypatch):
    import ui.runner as runner_module

    user = _user(user_id="finisher")
    run_id = quota.reserve(user, db_path=db)
    monkeypatch.setattr(config, "SQLITE_PATH", db)

    runner = runner_module.SessionRunner(session_id="s1", topic="t")
    runner.run_id = run_id
    monkeypatch.setattr(runner, "_run", lambda: None)
    runner._safe_run()
    runner._settle_run("completed")               # a second attempt changes nothing

    assert quota.allowance(user, db_path=db).used == 1
