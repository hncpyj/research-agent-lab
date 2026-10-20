"""
Legacy experiment-code generation (briefs without a declared dataset) and the
local-model output budget.

Sessions whose brief declares a dataset no longer reach this code: they go
through the study stages in ui/study_runner.py. The statistics template that
used to live here (tools/panel_setup.py) ran one fixed analysis whatever the
hypothesis said, and was removed on 2026-09-14.
"""
from unittest.mock import MagicMock, patch

import pytest

from agents.experiment_agent import ExperimentAgent, UnsupportedExperimentError


def _agent(session):
    api = MagicMock()
    api.generate.return_value = "print('ok')"
    note_db = MagicMock()
    note_db.get_session.return_value = session
    note_db.get_degradations.return_value = []
    return ExperimentAgent(api_model=api, note_db=note_db, experiments_base_dir="experiments"), api, note_db


def test_an_unclassifiable_hypothesis_generates_nothing_and_says_why():
    agent, api, note_db = _agent({"background": "", "goals": "", "constraints": ""})
    hypothesis = {"content": "A completely unclassifiable idea xyzzy"}

    with pytest.raises(UnsupportedExperimentError):
        agent._generate_all_files(hypothesis, skip_paths=set(), session_id="s1")

    assert api.generate.call_count == 0          # nothing was written
    recorded = [c.args[1:4] for c in note_db.save_degradation.call_args_list]
    assert (5, "domain_routing", "critical") in recorded


def test_a_hypothesis_with_no_matching_dataset_stops_before_generating():
    """Which data an experiment runs on is the experiment; a default is a different one."""
    agent, api, note_db = _agent({"background": "", "goals": "", "constraints": ""})
    hypothesis = {"content": "PPO policy gradient sparse reward environments"}   # routes to RL

    from tools.dataset_resolver import DatasetUnresolved
    with patch("tools.dataset_resolver.resolve", side_effect=DatasetUnresolved("nothing fits")):
        with pytest.raises(UnsupportedExperimentError, match="nothing fits"):
            agent._generate_all_files(hypothesis, skip_paths=set(), session_id="s1")

    assert api.generate.call_count == 0
    recorded = [c.args[1:4] for c in note_db.save_degradation.call_args_list]
    assert (5, "dataset_resolver", "critical") in recorded


def test_local_fallback_passes_the_output_budget_through():
    from models.api_model import APIModel

    api = APIModel(api_key="")
    local = MagicMock(is_loaded=True, _resolved_model="llama3.1:8b")
    local.generate.return_value = "code"
    api.set_local_model(local)
    api._tracker = MagicMock()

    api.generate("short prompt", system="s", task_type="CODE_GENERATION", max_tokens=8192)

    out = local.generate.call_args.kwargs["max_tokens"]
    assert 2048 < out <= 8192  # no longer silently capped at LOCAL_MAX_TOKENS


def test_local_output_budget_leaves_room_for_a_long_prompt():
    import config
    from models.api_model import APIModel

    api = APIModel(api_key="")
    local = MagicMock(is_loaded=True, _resolved_model="llama3.1:8b")
    local.generate.return_value = "x"
    api.set_local_model(local)
    api._tracker = MagicMock()
    long_prompt = "w " * 9000  # ~18k chars

    api.generate(long_prompt, system="s", task_type="GAP_ANALYSIS", max_tokens=8192)

    out = local.generate.call_args.kwargs["max_tokens"]
    assert out + len(long_prompt) // 3 <= config.OLLAMA_NUM_CTX
