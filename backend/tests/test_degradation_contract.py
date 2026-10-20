"""
The degradation contract: a guarded step that exits without confirming
success is recorded as critical — whatever the exit path.

Background: four separate silent failures (ranking no-op, 0 canon papers,
0 api_usage_log rows, and on 2026-09-13 a data check that returned early and
skipped its "[Data check ...]" label) each needed someone to remember to
report on that specific code path. The guard removes the need to remember:
early return, exception, or a forgotten ok() all leave a record.
"""
from unittest.mock import MagicMock

import pytest

from agents.degradation import DegradationLog


def _log():
    db = MagicMock()
    db.get_degradations.return_value = []
    return DegradationLog(db, "sess-1"), db


def _recorded(db):
    return [c.args[1:4] for c in db.save_degradation.call_args_list]


def test_confirmed_step_records_nothing():
    log, db = _log()
    with log.phase(3, "data_check") as gate:
        gate.ok()
    assert _recorded(db) == []


def test_exiting_without_ok_is_recorded_as_critical():
    log, db = _log()
    with log.phase(3, "data_check"):
        pass
    assert (3, "data_check", "critical") in _recorded(db)


def test_early_return_is_recorded_as_critical():
    log, db = _log()

    def step():
        with log.phase(3, "data_check") as gate:
            if True:
                return "left early"
            gate.ok()

    assert step() == "left early"
    assert (3, "data_check", "critical") in _recorded(db)


def test_exception_is_recorded_and_still_raised():
    log, db = _log()
    with pytest.raises(ValueError):
        with log.phase(3, "data_check") as gate:
            raise ValueError("bad JSON")
            gate.ok()  # noqa: unreachable on purpose
    recorded = [c for c in db.save_degradation.call_args_list if c.args[1:4] == (3, "data_check", "critical")]
    assert recorded and "bad JSON" in recorded[0].args[4]


def test_explicit_failure_reason_is_kept():
    log, db = _log()
    with log.phase(3, "data_check") as gate:
        gate.fail("model output could not be parsed")
    recorded = [c for c in db.save_degradation.call_args_list if c.args[1:4] == (3, "data_check", "critical")]
    assert "model output could not be parsed" in recorded[0].args[4]


def test_ai_judge_failure_is_recorded():
    from unittest.mock import MagicMock
    from agents.quality_review import QualityReviewAgent

    api = MagicMock()
    api.generate_structured.return_value = "not json"
    note_db = MagicMock()
    agent = QualityReviewAgent(api_model=api, note_db=note_db)

    judge = agent._ai_judge_review("t", [], [], {}, {}, "", [], session_id="s1")

    assert judge["findings"] == []
    assert note_db.save_degradation.call_args.args[1:4] == (7, "ai_judge", "critical")
