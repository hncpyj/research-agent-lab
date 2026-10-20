"""
M0 — things that let an experiment look done or look like someone else's work
(found reading the post-gap stages on 2026-09-14).
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import config
from agents import experiment_runner as runner_mod
from agents.quality_review import REVIEWER_PERSONAS, QualityReviewAgent
from agents.report_agent import ReportAgent
from agents.self_bugfix_agent import SelfBugFixAgent

ROOT = Path(__file__).resolve().parent.parent


def test_fix_prompt_no_longer_asks_for_simulated_or_placeholder_results():
    text = (runner_mod._FIX_SYSTEM + runner_mod._FIX_PROMPT).lower()
    assert "plausible" not in text and "implement a complete numpy-only simulation" not in text
    assert "never generate synthetic, simulated, random or placeholder data" in text


def test_reviewer_personas_are_anonymous_and_do_not_impersonate_people():
    assert REVIEWER_PERSONAS
    assert all(p["name"].startswith("Reviewer ") for p in REVIEWER_PERSONAS)
    assert all(not p.get("quote") for p in REVIEWER_PERSONAS)
    assert all(not p.get("person_name") for p in REVIEWER_PERSONAS)


def test_missing_script_fails_the_phase(tmp_path):
    db = MagicMock()
    agent = runner_mod.ExperimentRunnerAgent(api_model=MagicMock(), note_db=db, experiments_base_dir=tmp_path)
    with pytest.raises(RuntimeError, match="train.py not found"):
        agent._run_phase_script("s1", "h1", tmp_path, "train", "train.py", [], fixable=True)
    assert db.finish_experiment_run.call_args.args[1] == "failed"


def test_failed_evaluation_stops_the_run(tmp_path):
    (tmp_path / "evaluate.py").write_text("import sys; sys.exit(3)\n")
    db = MagicMock()
    agent = runner_mod.ExperimentRunnerAgent(api_model=MagicMock(), note_db=db, experiments_base_dir=tmp_path,
                                             python_executable=__import__("sys").executable)
    with pytest.raises(RuntimeError, match="exit code 3"):
        agent._run_phase_script("s1", "h1", tmp_path, "evaluate", "evaluate.py", [], fixable=False)


def test_experiment_folder_is_the_sessions_own(tmp_path):
    db = MagicMock()
    db.get_hypotheses.return_value = [{"hypothesis_id": "h1", "status": "code_generated"}]
    other = tmp_path / "hypothesis_1"
    other.mkdir()
    (other / "config.yaml").write_text("x: 1")
    agent = runner_mod.ExperimentRunnerAgent(api_model=MagicMock(), note_db=db, experiments_base_dir=tmp_path)
    _, folder, _ = agent._resolve_experiment("session-abc")
    assert folder == tmp_path / "session-abc"


def test_review_and_report_read_only_this_sessions_results(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path)
    archived = tmp_path / "_archive" / "old" / "results"
    archived.mkdir(parents=True)
    (archived / "eval_results.json").write_text('{"mean_return": 1}')
    assert QualityReviewAgent(api_model=MagicMock(), note_db=MagicMock())._load_eval_results("new-session") == {}
    eval_str, _ = ReportAgent(api_model=MagicMock(), note_db=MagicMock())._load_eval_results("new-session")
    assert "mean_return" not in eval_str


def test_retry_wrapper_does_not_pass_arguments_the_phase_does_not_take(monkeypatch):
    import agents.self_bugfix_agent as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    calls = []

    def phase(a):
        calls.append(a)
        if len(calls) == 1:
            raise KeyError("missing")
        return "ok"

    wrapper = SelfBugFixAgent(api_model=MagicMock())
    wrapper._generate_hint = MagicMock(return_value="hint")
    assert wrapper.wrap("P", phase, 1) == "ok"
    wrapper._generate_hint.assert_not_called()


def test_no_model_report_contains_no_text_from_another_project():
    report = ReportAgent._template_report({"topic": "Clean cooking", "eval_results": "{}"})
    text = " ".join(str(v) for v in report.values()).lower()
    for phrase in ("contrastive", "dualencoder", "recall@", "retrieval", "nt-xent"):
        assert phrase not in text
