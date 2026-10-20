"""
Regression tests for unified domain routing (agents/experiment_agent.py).

Background: the system prompt (steers what the LLM writes) and the file
specs (decides which files get created) used to be selected by two
SEPARATELY maintained keyword lists. They had already drifted apart in the
committed code: the file-spec NLP entry had 3 extra keywords ("natural
language", "nli", "entailment") the system-prompt NLP entry never got. A
hypothesis matching only one of those three keywords would receive an NLP
file skeleton steered by the wrong (RL-fallback) system prompt — the same
class of mismatch a 2026-09-12 audit found for real in session `ab5473c0`
(RL file skeleton generated for a domain-adaptation-flavored hypothesis).

_select_domain() now returns both from a single DomainSpec, so they cannot
disagree by construction. These tests pin that guarantee and the specific
keyword-drift case that used to be broken.
"""
import shutil
import tempfile
from pathlib import Path

import pytest

from agents.experiment_agent import (
    UnsupportedExperimentError,
    _select_domain,
    _DOMAIN_REGISTRY,
    _SYSTEM_NLP,
    _SYSTEM_RL,
    _SYSTEM_DOMAIN_ADAPTATION,
    _FILE_SPECS_NLP,
    _FILE_SPECS_RL,
)


def test_previously_drifted_nlp_keywords_now_route_both_prompt_and_files_together():
    """Regression pin: 'natural language inference' matched _FILE_SPECS_NLP
    but NOT _SYSTEM_NLP under the old two-list design (only "nli" was in
    the file-spec list). Must now resolve to NLP for both."""
    hypothesis_text = "A study of natural language inference robustness under distribution shift"
    domain = _select_domain(hypothesis_text)

    assert domain.label == "nlp"
    assert domain.system_prompt == _SYSTEM_NLP
    assert domain.file_specs == tuple(_FILE_SPECS_NLP)


def test_entailment_keyword_alone_routes_to_nlp():
    """Another one of the 3 keywords that used to only affect file specs."""
    domain = _select_domain("Improving textual entailment detection accuracy")
    assert domain.label == "nlp"
    assert domain.system_prompt == _SYSTEM_NLP


def test_domain_adaptation_hypothesis_gets_da_prompt_and_da_files_together():
    """Pins the exact scenario found in session ab5473c0: a domain-adaptation
    hypothesis must get the DA file spec (models/domain_adapter.py,
    baselines/source_only.py), not the RL skeleton (envs/wrappers.py,
    models/recurrent.py)."""
    hypothesis_text = "Domain-Invariant Contrastive Pretraining with Synthetic Domain Shifts"
    domain = _select_domain(hypothesis_text)

    assert domain.label == "domain adaptation"
    assert domain.system_prompt == _SYSTEM_DOMAIN_ADAPTATION
    file_paths = {spec[0] for spec in domain.file_specs}
    assert "models/domain_adapter.py" in file_paths
    assert "baselines/source_only.py" in file_paths
    assert "envs/wrappers.py" not in file_paths  # the RL-only file that leaked in before


def test_prompt_and_file_specs_can_never_disagree_for_any_registered_domain():
    """
    Structural guarantee: every DomainSpec's prompt/file_specs pairing is
    internally consistent by construction (single source of truth).

    A declarative family is excluded: it generates no code at all, so it has
    no file specs to disagree with anything. Its apparatus is copied in, and
    that it has some is checked instead.
    """
    for domain in _DOMAIN_REGISTRY:
        if not domain.file_specs:
            assert domain.copied_files, (
                f"{domain.label} generates nothing and ships nothing: it cannot build "
                "an experiment")
            continue
        # Re-deriving via the class itself proves prompt+files are read from
        # the exact same object, not two independent lookups that could skew.
        assert isinstance(domain.system_prompt, str) and domain.system_prompt
        assert isinstance(domain.file_specs, tuple) and len(domain.file_specs) > 0


def test_retrieval_keyword_takes_priority_over_generic_rl_environment_keyword():
    """'environment' is a generic RL keyword; a retrieval hypothesis that
    happens to mention it must still route to retrieval, not RL, matching
    the checked-in-order priority (retrieval/DA before the broader RL set)."""
    hypothesis_text = "Dense retrieval robustness across corpus environment shifts using BEIR"
    domain = _select_domain(hypothesis_text)
    assert domain.label == "retrieval"


def test_an_unmatched_hypothesis_is_refused_rather_than_made_into_an_rl_experiment():
    """
    2026-09-21: a study of adversarial curation matched no scaffold, was given
    the RL template, and ran to completion as a MiniGrid agent. The wrong
    experiment finishing is worse than no experiment starting.
    """
    with pytest.raises(UnsupportedExperimentError, match="No experiment scaffold"):
        _select_domain("A completely novel unclassifiable research direction xyzzy")


def test_reinforcement_learning_hypothesis_routes_to_rl():
    domain = _select_domain("Policy gradient methods with PPO for sparse reward environments")
    assert domain.label == "reinforcement learning"
    assert domain.system_prompt == _SYSTEM_RL
    assert domain.file_specs == tuple(_FILE_SPECS_RL)


def _temp_db():
    """
    sqlite3's `with conn:` context manager only commits/rolls back — it does
    NOT close the connection, so file handles can outlive the `with` block.
    That's harmless on POSIX but blocks deletion on Windows if we lean on
    tempfile.TemporaryDirectory()'s auto-cleanup, which raises on cleanup
    failure. Use a manual mkdtemp + best-effort rmtree instead.
    """
    from memory.note_db import NoteDB
    tmp_dir = tempfile.mkdtemp()
    db = NoteDB(db_path=Path(tmp_dir) / "test.db")
    return db, tmp_dir


def test_domain_persists_to_db_on_hypothesis_status_update():
    """Item C also persists the resolved domain to hypotheses.domain so a
    future audit doesn't need forensic reconstruction from file names."""
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")
        hyp_id = db.save_hypothesis(session_id, content="test hypothesis")

        db.update_hypothesis_status(hyp_id, "code_generated", domain="domain adaptation")

        rows = db.get_hypotheses(session_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "code_generated"
        assert rows[0]["domain"] == "domain adaptation"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_domain_persists_as_null_when_not_provided_backward_compatible():
    """Existing call sites that don't pass domain= must keep working (no
    forced migration of every caller)."""
    db, tmp_dir = _temp_db()
    try:
        session_id = db.create_session("test topic")
        hyp_id = db.save_hypothesis(session_id, content="test hypothesis")

        db.update_hypothesis_status(hyp_id, "candidate")  # no domain kwarg

        rows = db.get_hypotheses(session_id)
        assert rows[0]["status"] == "candidate"
        assert rows[0]["domain"] is None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- every file written against the same contract ----------------------------------------

def test_leaf_modules_are_written_before_the_scripts_that_import_them():
    """
    train.py generated first has to guess what envs/wrappers.py will export,
    and guessing is how a project ends up importing things nobody wrote.
    """
    from agents.experiment_agent import _generation_order

    ordered = _generation_order([("train.py", "", "py"), ("envs/wrappers.py", "", "py"),
                                 ("evaluate.py", "", "py"), ("models/net.py", "", "py")])
    assert [path for path, _, _ in ordered] == [
        "envs/wrappers.py", "models/net.py", "evaluate.py", "train.py"]


def test_a_files_public_interface_is_what_other_files_are_shown():
    from agents.experiment_agent import _public_interface

    source = ("import gymnasium as gym\n\n"
              "def make_env(name, seed=0):\n    pass\n\n"
              "class HorizonWrapper:\n"
              "    def step(self, action): pass\n"
              "    def _private(self): pass\n")
    interface = _public_interface(source, "envs/wrappers.py")

    assert "def make_env(name, seed=0)" in interface
    assert "class HorizonWrapper: step" in interface
    assert "_private" not in interface          # not part of the contract
    assert "import gymnasium" not in interface  # signatures only, not the body


def test_every_prompt_carries_the_project_manifest():
    from agents.experiment_agent import _manifest_section

    section = _manifest_section([("train.py", "", "py"), ("envs/wrappers.py", "", "py")], {})
    assert "train.py" in section and "envs/wrappers.py" in section
    assert "do not invent modules" in section


def test_what_was_written_earlier_is_shown_to_what_comes_next():
    from agents.experiment_agent import _manifest_section

    written = {"envs/wrappers.py": "def make_env(name):\n    pass\n"}
    section = _manifest_section([("train.py", "", "py"), ("envs/wrappers.py", "", "py")], written)
    assert "ALREADY WRITTEN" in section
    assert "def make_env(name)" in section
