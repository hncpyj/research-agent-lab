"""
A daily cap on API spend (config.API_DAILY_BUDGET_USD).

2026-09-20 product audit: nothing limited what a run could spend, and a run
that exhausted its credit mid-way switched to the local model with the switch
visible only in a log file.
"""
from datetime import datetime, timedelta

import pytest

import config
from models.api_model import APIModel
from tools.cost_tracker import CostTracker


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    # The cap can also come from the settings page; point that at an empty
    # folder so these tests are about config, not about this machine's file.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return CostTracker(db_path=tmp_path / "usage.db")


def _spend(tracker, usd, when=None):
    """Write one row costing roughly `usd` (sonnet output is $15 per 1M tokens)."""
    tracker.log("claude-sonnet-4-5", 0, int(usd / 15.0 * 1_000_000), "test")
    if when:
        with tracker._connect() as conn:
            conn.execute("UPDATE api_usage_log SET timestamp = ? WHERE id = (SELECT MAX(id) FROM api_usage_log)",
                         (when,))


def test_spend_today_ignores_earlier_days(tracker):
    _spend(tracker, 2.0, when=(datetime.utcnow() - timedelta(days=3)).isoformat(timespec="seconds"))
    _spend(tracker, 1.0)
    assert tracker.total_cost() == pytest.approx(3.0, abs=0.01)
    assert tracker.spend_today() == pytest.approx(1.0, abs=0.01)


def test_no_cap_means_no_limit(tracker, monkeypatch):
    monkeypatch.setattr(config, "API_DAILY_BUDGET_USD", 0.0)
    _spend(tracker, 100.0)
    assert APIModel(api_key="", cost_tracker=tracker).over_budget() is False


def test_calls_stop_at_the_cap_and_the_run_is_told(tracker, monkeypatch):
    monkeypatch.setattr(config, "API_DAILY_BUDGET_USD", 5.0)
    told: list[tuple[float, float]] = []
    model = APIModel(api_key="", cost_tracker=tracker, on_budget_stop=lambda s, c: told.append((s, c)))

    _spend(tracker, 4.0)
    assert model.over_budget() is False and told == []

    _spend(tracker, 1.5)
    assert model.over_budget() is True
    assert model.over_budget() is True          # still capped
    assert len(told) == 1                       # said once, not on every call
    spent, cap = told[0]
    assert spent == pytest.approx(5.5, abs=0.01) and cap == 5.0


def test_a_capped_model_answers_from_the_local_model(tracker, monkeypatch):
    monkeypatch.setattr(config, "API_DAILY_BUDGET_USD", 1.0)
    _spend(tracker, 2.0)

    class _Local:
        is_loaded = True
        def generate(self, prompt, system="", max_tokens=0, temperature=0.0, **kw):
            return "answered locally"

    model = APIModel(api_key="test-key", cost_tracker=tracker, local_model=_Local())
    assert model.generate("hi", task_type="test") == "answered locally"


def test_cost_is_attributed_to_the_session_that_spent_it(tracker):
    """The session view showed the all-time total, so an empty session looked expensive."""
    tracker.log("claude-sonnet-4-5", 1_000_000, 0, "gap", session_id="session-a")   # $3.00
    tracker.log("claude-sonnet-4-5", 1_000_000, 0, "gap", session_id="session-b")   # $3.00
    tracker.log("local:llama3.1", 100, 100, "report", is_local=True, session_id="session-a")

    a = tracker.session_cost("session-a")
    assert a["cost_usd"] == pytest.approx(3.0, abs=0.01)
    assert a["calls"] == 2 and a["local_calls"] == 1 and a["attributed"] is True
    assert tracker.session_cost("session-b")["cost_usd"] == pytest.approx(3.0, abs=0.01)
    assert tracker.total_cost() == pytest.approx(6.0, abs=0.01)


def test_a_session_from_before_this_change_says_so_instead_of_showing_zero(tracker):
    tracker.log("claude-sonnet-4-5", 1_000_000, 0, "gap")      # no session recorded
    old = tracker.session_cost("some-old-session")
    assert old["calls"] == 0 and old["attributed"] is False
    assert tracker.total_cost() > 0                            # the money is still in the total
