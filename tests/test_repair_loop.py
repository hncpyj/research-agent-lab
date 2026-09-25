"""
Reading the traceback, and not asking the same question three times.

2026-09-21, from a real run: a study that matched no scaffold was generated as
a reinforcement-learning codebase against a news-classification dataset — both
recorded as critical, both ignored — and then failed at
`AttributeError: module 'gymnasium' has no attribute 'Tuple'`, raised in
`envs/wrappers.py` line 11. The repair loop rewrote `train.py` three times. The
first and third left the cause untouched; the second invented
`from gymnasium import Tuple`.

Four things had to change, and these pin them: the culprit comes from the
traceback, the same failure twice changes the approach rather than spending a
turn, code is checked before it is run, and a critically degraded session does
not run at all.
"""
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import config
from agents import error_diagnostics as diag
from agents import preflight

REAL_TRACEBACK = textwrap.dedent("""\
    Traceback (most recent call last):
      File "C:\\exp\\hypothesis_1\\train.py", line 84, in <module>
        main(cfg)
      File "C:\\exp\\hypothesis_1\\train.py", line 61, in main
        obs, reward, done, truncated, info = env.step(action)
      File "C:\\Python312\\site-packages\\gymnasium\\core.py", line 515, in step
        return self.env.step(action)
      File "C:\\exp\\hypothesis_1\\envs\\wrappers.py", line 11, in step
        def step(self, action) -> gym.Tuple[Any, float, bool, bool, Dict]:
    AttributeError: module 'gymnasium' has no attribute 'Tuple'
""")


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    folder = tmp_path / "hypothesis_1"
    (folder / "envs").mkdir(parents=True)
    (folder / "train.py").write_text("import envs.wrappers\nprint('training')\n", encoding="utf-8")
    (folder / "envs" / "__init__.py").write_text("", encoding="utf-8")
    (folder / "envs" / "wrappers.py").write_text("x = 1\n", encoding="utf-8")
    return folder


# --- reading the traceback ------------------------------------------------------------

def test_the_culprit_is_the_deepest_file_the_project_owns():
    found = diag.culprit(REAL_TRACEBACK, Path("C:/exp/hypothesis_1"))
    assert found is not None
    assert Path(found.file).name == "wrappers.py"
    assert found.line == 11 and found.symbol == "step"


def test_a_library_frame_is_never_the_culprit():
    """gymnasium did nothing wrong by not having a Tuple; the wrapper asked for one."""
    found = diag.culprit(REAL_TRACEBACK, Path("C:/exp/hypothesis_1"))
    assert "site-packages" not in found.file


def test_a_traceback_with_no_project_frames_has_no_culprit():
    only_library = ('  File "C:\\Python312\\site-packages\\torch\\x.py", line 3, in f\n'
                    "RuntimeError: CUDA out of memory\n")
    assert diag.culprit(only_library, Path("C:/exp/hypothesis_1")) is None


def test_two_runs_of_the_same_fault_have_the_same_fingerprint():
    first = diag.fingerprint(REAL_TRACEBACK, Path("C:/exp/hypothesis_1"))
    # A rerun: different line numbers above it, same fault.
    second = diag.fingerprint(REAL_TRACEBACK.replace("line 84", "line 91"),
                              Path("C:/exp/hypothesis_1"))
    assert first == second
    assert first.exception_type == "AttributeError"
    assert first.culprit_file == "envs/wrappers.py" and first.culprit_symbol == "step"


def test_a_different_fault_in_the_same_file_is_a_different_fingerprint():
    other = REAL_TRACEBACK.replace(
        "AttributeError: module 'gymnasium' has no attribute 'Tuple'",
        "ValueError: expected 4 values, got 5")
    assert (diag.fingerprint(REAL_TRACEBACK, Path("C:/exp/hypothesis_1"))
            != diag.fingerprint(other, Path("C:/exp/hypothesis_1")))


def test_numbers_that_change_between_runs_do_not_change_the_fingerprint():
    a = ('  File "C:\\exp\\hypothesis_1\\train.py", line 3, in main\n'
         "ValueError: shape mismatch: got 32 expected 64\n")
    b = ('  File "C:\\exp\\hypothesis_1\\train.py", line 3, in main\n'
         "ValueError: shape mismatch: got 16 expected 128\n")
    assert (diag.fingerprint(a, Path("C:/exp/hypothesis_1"))
            == diag.fingerprint(b, Path("C:/exp/hypothesis_1")))


def test_the_files_a_failing_file_imports_can_be_found(experiment):
    source = (experiment / "train.py").read_text(encoding="utf-8")
    assert diag.local_imports(source, experiment) == ["envs/wrappers.py"]


# --- planning the repair ---------------------------------------------------------------

def _agent():
    from agents.experiment_runner import ExperimentRunnerAgent

    return ExperimentRunnerAgent(api_model=MagicMock(), note_db=MagicMock(),
                                 experiments_base_dir=Path("experiments"))


def test_the_file_the_traceback_names_is_the_file_that_gets_fixed(experiment):
    """The whole failure: three rewrites of train.py while wrappers.py stayed broken."""
    traceback = REAL_TRACEBACK.replace("C:\\exp\\hypothesis_1", str(experiment).replace("/", "\\"))
    plan = _agent()._plan_repair(experiment_dir=experiment,
                                 entry_script=experiment / "train.py",
                                 stderr=traceback, previous=None)
    assert plan["target"].name == "wrappers.py"
    assert plan["strategy"] == "local patch"


def test_the_same_failure_twice_changes_the_approach(experiment):
    agent = _agent()
    traceback = REAL_TRACEBACK.replace("C:\\exp\\hypothesis_1", str(experiment).replace("/", "\\"))

    first = agent._plan_repair(experiment, experiment / "train.py", traceback, None)
    second = agent._plan_repair(experiment, experiment / "train.py", traceback,
                                first["fingerprint"], first["strategy"])
    third = agent._plan_repair(experiment, experiment / "train.py", traceback,
                               second["fingerprint"], second["strategy"])

    assert [p["strategy"] for p in (first, second, third)] == [
        "local patch", "root cause", "regenerate"]


def test_a_new_failure_gets_the_cheap_targeted_attempt_again(experiment):
    """
    A different error means the last patch fixed the cause it was aimed at, so
    the new fault deserves the same small, targeted attempt the first one got —
    not the wider, more expensive question that being stuck earns.
    """
    agent = _agent()
    traceback = REAL_TRACEBACK.replace("C:\\exp\\hypothesis_1", str(experiment).replace("/", "\\"))
    moved_on = traceback.replace("AttributeError: module 'gymnasium' has no attribute 'Tuple'",
                                 "ValueError: expected 4 values, got 5")

    first = agent._plan_repair(experiment, experiment / "train.py", traceback, None)
    second = agent._plan_repair(experiment, experiment / "train.py", moved_on,
                                first["fingerprint"], first["strategy"])
    assert second["strategy"] == "local patch"


def test_a_root_cause_attempt_is_shown_what_the_file_imports(experiment):
    agent = _agent()
    (experiment / "envs" / "wrappers.py").write_text(
        "import envs.helpers\nx = 1\n", encoding="utf-8")
    (experiment / "envs" / "helpers.py").write_text("def helper(): pass\n", encoding="utf-8")
    traceback = REAL_TRACEBACK.replace("C:\\exp\\hypothesis_1", str(experiment).replace("/", "\\"))

    plan = agent._plan_repair(experiment, experiment / "train.py", traceback,
                              diag.fingerprint(traceback, experiment), "local patch")
    assert "envs/helpers.py" in plan["context"]
    assert "train.py (the script that was run)" in plan["context"]


def test_a_local_patch_is_not_buried_in_context(experiment):
    traceback = REAL_TRACEBACK.replace("C:\\exp\\hypothesis_1", str(experiment).replace("/", "\\"))
    plan = _agent()._plan_repair(experiment, experiment / "train.py", traceback, None, 1)
    assert plan["context"] == ""


def test_an_unreadable_traceback_falls_back_to_the_script_that_ran(experiment):
    plan = _agent()._plan_repair(experiment, experiment / "train.py",
                                 "Killed. Exit code 137.", None)
    assert plan["target"].name == "train.py"


# --- checking before running -------------------------------------------------------------

def test_a_syntax_error_is_caught_without_running_anything(experiment):
    (experiment / "envs" / "wrappers.py").write_text("def step(self:\n", encoding="utf-8")

    report = preflight.check(experiment)
    assert report.passed is False
    assert report.failures[0].stage == "compile"
    assert "wrappers.py" in report.failures[0].file


def test_the_gymnasium_fault_is_caught_by_importing_not_by_training(experiment):
    """The whole point of the ladder: seconds, no GPU, before install even matters."""
    (experiment / "envs" / "wrappers.py").write_text(
        "import sys\nraise AttributeError(\"module 'gymnasium' has no attribute 'Tuple'\")\n",
        encoding="utf-8")

    report = preflight.check(experiment)
    assert report.passed is False
    assert report.failures[0].stage == "imports"
    assert "gymnasium" in report.failures[0].message


def test_good_code_passes(experiment):
    report = preflight.check(experiment)
    assert report.passed is True and "imports" in report.ran


def test_an_entry_script_is_not_imported(experiment):
    """Importing train.py would start the training this ladder exists to avoid."""
    (experiment / "train.py").write_text("raise SystemExit('training started')\n", encoding="utf-8")
    assert preflight.check(experiment).passed is True


def test_nothing_is_imported_where_execution_is_not_allowed(experiment, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", False)
    (experiment / "envs" / "wrappers.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    report = preflight.check(experiment)
    assert report.passed is True            # compile passed
    assert "imports" in report.skipped      # and it says what it did not do


def test_an_empty_folder_is_a_failure_not_a_pass(tmp_path):
    assert preflight.check(tmp_path).passed is False


# --- the session's own record is part of preflight ------------------------------------

def _db_with(degradations):
    db = MagicMock()
    db.get_degradations.return_value = degradations
    return db


def test_a_critically_degraded_session_does_not_run(experiment):
    db = _db_with([{"phase": 5, "severity": "critical", "component": "domain_routing",
                    "message": "No domain template matched the hypothesis."}])

    report = preflight.check(experiment, db=db, session_id="s1")
    assert report.passed is False
    assert report.failures[0].stage == "spec"
    assert "No domain template matched" in report.failures[0].message


def test_a_warning_does_not_stop_a_run(experiment):
    db = _db_with([{"phase": 5, "severity": "warning", "component": "x", "message": "minor"}])
    assert preflight.check(experiment, db=db, session_id="s1").passed is True


def test_the_blocked_run_says_why_in_one_sentence(experiment):
    db = _db_with([{"phase": 5, "severity": "critical", "component": "dataset_resolver",
                    "message": "No dataset matched the hypothesis."}])
    with pytest.raises(preflight.PreflightBlocked) as blocked:
        preflight.require(experiment, db=db, session_id="s1")
    assert "No dataset matched" in str(blocked.value)


# --- the loop, end to end ---------------------------------------------------------------

def test_the_run_from_the_log_would_now_fix_the_right_file(experiment, monkeypatch, tmp_path):
    """
    A rehearsal of the 2026-09-21 failure: train.py fails, the traceback blames
    envs/wrappers.py. The fix must land in wrappers.py, once, and the attempt
    must be recorded with what it achieved.
    """
    from unittest.mock import MagicMock

    from agents.experiment_runner import ExperimentRunnerAgent
    from memory import repair_log

    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    traceback = REAL_TRACEBACK.replace("C:\exp\hypothesis_1", str(experiment).replace("/", "\\"))
    db = MagicMock()
    db.create_experiment_run.return_value = "run-1"
    db.get_degradations.return_value = []
    api = MagicMock()
    api.generate.return_value = "from typing import Tuple\nx = 1\n"

    agent = ExperimentRunnerAgent(api_model=api, note_db=db, experiments_base_dir=tmp_path,
                                  max_fix_attempts=1)

    # This unit test isolates culprit selection. Production repair permission
    # is covered separately by test_production_control_integration.py.
    from agents import control_boundary
    from agents.build_manifest import BuildManifest
    from agents.experiment_agent import build_spec
    from agents.study_protocol import StudyProtocol
    repair_spec = build_spec(
        "BERT improves text classification accuracy on AG News relative to a baseline.")
    monkeypatch.setattr(StudyProtocol, "read",
                        classmethod(lambda cls, folder: repair_spec))
    monkeypatch.setattr(BuildManifest, "read", classmethod(lambda cls, folder: MagicMock()))
    monkeypatch.setattr(control_boundary, "authorize_built_study", lambda *_a, **_k: {})

    calls = {"n": 0}

    def fail_then_pass(cmd, cwd, timeout, phase_label):
        calls["n"] += 1
        if calls["n"] == 1:
            return "", traceback, 1
        return "done", "", 0

    monkeypatch.setattr(agent, "_stream_subprocess", fail_then_pass)
    agent._run_phase_script(session_id="s1", hypothesis_id="h1", experiment_dir=experiment,
                            phase="train", script="train.py", extra_args=[], fixable=True)

    assert (experiment / "envs" / "wrappers.py").read_text(encoding="utf-8").startswith(
        "from typing import Tuple")                      # the culprit was the file rewritten
    assert (experiment / "train.py").read_text(encoding="utf-8").startswith("import envs")

    recorded = repair_log.history("s1")
    assert len(recorded) == 1
    assert recorded[0]["target_file"] == "envs/wrappers.py"
    assert recorded[0]["strategy"] == "local patch"
    assert recorded[0]["outcome"] == "fixed"


def test_a_patch_that_changes_nothing_is_recorded_as_such(experiment, monkeypatch, tmp_path):
    """`same_error` is the number to watch: money spent to stand still."""
    from unittest.mock import MagicMock

    from agents.experiment_runner import ExperimentRunnerAgent
    from memory import repair_log

    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    traceback = REAL_TRACEBACK.replace("C:\exp\hypothesis_1", str(experiment).replace("/", "\\"))
    db = MagicMock()
    db.create_experiment_run.return_value = "run-1"
    api = MagicMock()
    api.generate.return_value = "x = 1\n"

    agent = ExperimentRunnerAgent(api_model=api, note_db=db, experiments_base_dir=tmp_path,
                                  max_fix_attempts=2)
    from agents import control_boundary
    from agents.build_manifest import BuildManifest
    from agents.experiment_agent import build_spec
    from agents.study_protocol import StudyProtocol
    repair_spec = build_spec(
        "BERT improves text classification accuracy on AG News relative to a baseline.")
    monkeypatch.setattr(StudyProtocol, "read",
                        classmethod(lambda cls, folder: repair_spec))
    monkeypatch.setattr(BuildManifest, "read", classmethod(lambda cls, folder: MagicMock()))
    monkeypatch.setattr(control_boundary, "authorize_built_study", lambda *_a, **_k: {})
    monkeypatch.setattr(agent, "_stream_subprocess",
                        lambda cmd, cwd, timeout, phase_label: ("", traceback, 1))

    with pytest.raises(RuntimeError, match="failed after"):
        agent._run_phase_script(session_id="s2", hypothesis_id="h1", experiment_dir=experiment,
                                phase="train", script="train.py", extra_args=[], fixable=True)

    recorded = repair_log.history("s2")
    assert [r["strategy"] for r in recorded] == ["local patch", "root cause"]
    assert recorded[0]["outcome"] == "same_error"       # the patch reached nothing
    assert repair_log.summary()["wasted"] >= 1


# --- what the person reading the page is told -------------------------------------------

def test_a_stopped_run_explains_itself_without_a_traceback():
    """
    `AttributeError: module 'gymnasium' has no attribute 'Tuple'` is the right
    thing to keep and the wrong thing to lead with.
    """
    from agents.preflight import PreflightBlocked, PreflightReport, Failure as PFailure
    from ui.failures import describe

    report = PreflightReport(passed=False, failures=[
        PFailure(stage="imports", file="envs/wrappers.py",
                 message="AttributeError: module 'gymnasium' has no attribute 'Tuple'")])
    told = describe(PreflightBlocked(report)).as_dict()

    assert told["title"] == "The experiment was not run"
    assert "cannot be trusted" in told["message"]
    assert "Nothing already saved is lost" in told["message"]
    assert "AttributeError" in told["detail"]          # kept, but underneath
    assert "AttributeError" not in told["message"]


def test_a_refused_fix_says_why_it_was_refused():
    from agents.experiment_runner import RepairRefused
    from ui.failures import describe

    told = describe(RepairRefused("the fix would read something else"))
    assert told.kind == "repair_refused"
    assert "changed what the experiment measures" in told.message


def test_an_unsupported_question_is_not_offered_a_retry():
    from agents.experiment_agent import UnsupportedExperimentError
    from ui.failures import describe

    told = describe(UnsupportedExperimentError("no scaffold"))
    assert told.can_retry is False                     # retrying changes nothing
    assert "different question" in told.message


def test_an_unexpected_error_still_gets_a_sentence_and_keeps_the_detail():
    from ui.failures import describe

    told = describe(ZeroDivisionError("division by zero"))
    assert told.title == "The run stopped with an error"
    assert told.detail == "ZeroDivisionError: division by zero"
