"""
Regression tests for the quality-review re-scoping (item E of the roadmap).

Background: the roadmap originally said "move QualityReviewAgent earlier,
right after Phase 3" — but on inspection, all of QualityReviewAgent's checks
need Phase 5/6 artifacts (code files, eval results) that don't exist at
Phase 3, so that's impossible as stated. Re-scoped to what's actually
useful: a fast pre_execution_check() using only the two checks that don't
need eval data (code-domain-alignment, baselines), run right after Phase 5
so a wrong-domain codebase is caught before Phase 6 burns compute on it.

Also fixes a THIRD instance of the same substring-matching bug found in item
C (agents/experiment_agent.py's old _select_system_prompt): "research"
contains "search" and would false-positive-match the retrieval
domain-alignment rule for any topic containing the ordinary word "research".
"""
from unittest.mock import MagicMock

from agents.quality_review import QualityReviewAgent, DOMAIN_ALIGNMENT_RULES


def _agent(topic: str, code_files: dict[str, str]):
    ndb = MagicMock()
    ndb.get_session.return_value = {"topic": topic}
    ndb.get_session_experiment_code.return_value = [
        {"file_path": path, "file_content": content}
        for path, content in code_files.items()
    ]
    agent = QualityReviewAgent(api_model=MagicMock(), note_db=ndb)
    return agent


def test_pre_execution_check_catches_rl_code_in_retrieval_hypothesis():
    """Pins the exact ab5473c0-shaped scenario: a retrieval topic that got
    an RL-flavored codebase (gymnasium import) must fail immediately,
    without needing any eval_results.json (which wouldn't exist yet)."""
    agent = _agent(
        topic="cross-domain retrieval generalization",
        code_files={
            "envs/wrappers.py": "import gymnasium as gym\nclass HorizonWrapper(gym.Wrapper): pass",
        },
    )

    report = agent.pre_execution_check("session-1")

    # The orchestrator/runner wiring iterates report.fails directly — that's
    # the invariant that matters, not the aggregate gate (which also factors
    # in the separate baseline-presence check and can land on "warn" even
    # with a domain-alignment fail present).
    assert any(f.criterion == "code_domain_alignment" and f.level == "fail" for f in report.fails)


def test_pre_execution_check_passes_clean_retrieval_code():
    agent = _agent(
        topic="dense passage retrieval for open-domain QA",
        code_files={
            "train.py": "from beir import util\nimport faiss\n"
                        "recall_at_10 = 0.8\nmrr = 0.5\nndcg = 0.6\n"
                        "bm25_baseline = True\nsbert_model = 'bert'\ndpr_encoder = True",
        },
    )

    report = agent.pre_execution_check("session-1")

    domain_findings = [f for f in report.findings if f.criterion == "code_domain_alignment"]
    assert all(f.level == "pass" for f in domain_findings)


def test_pre_execution_check_does_not_require_eval_data():
    """The whole point of the re-scoped check: it must work with only code
    files, before any experiment has run and produced eval_results.json."""
    agent = _agent(topic="some topic", code_files={"train.py": "print('hi')"})
    # Should not raise even though no eval_results.json exists anywhere
    report = agent.pre_execution_check("session-1")
    assert report.session_id == "session-1"


def test_research_word_no_longer_false_positive_matches_retrieval_rule():
    """Regression pin for the third instance of the "research" ⊃ "search"
    substring bug (first found in agents/experiment_agent.py, item C)."""
    agent = _agent(
        topic="A survey of research methodology in deep learning",  # contains "research", not retrieval-related
        code_files={"train.py": "import torch\nmodel = torch.nn.Linear(10, 1)"},
    )

    report = agent.pre_execution_check("session-1")

    # The retrieval rule must NOT have fired at all for this topic.
    retrieval_rule = DOMAIN_ALIGNMENT_RULES[0]
    assert "search" in retrieval_rule["topic_keywords"]  # sanity: this is the rule that used to misfire
    domain_findings = [f for f in report.findings if f.criterion == "code_domain_alignment"]
    # No RL/retrieval-forbidden-import complaints should appear for plain torch code
    # under an irrelevant "research methodology" topic.
    assert not any(f.level == "fail" for f in domain_findings)


def test_actual_retrieval_keyword_still_matches_after_fix():
    """Make sure fixing the substring bug didn't break legitimate matches."""
    agent = _agent(
        topic="dense retrieval and ranking for search engines",
        code_files={
            "envs/wrappers.py": "import gymnasium as gym",  # still wrong-domain code
        },
    )
    report = agent.pre_execution_check("session-1")
    assert any(f.criterion == "code_domain_alignment" and f.level == "fail" for f in report.fails)


def test_full_review_still_works_with_new_import():
    """Make sure the review() method (used at Phase 7, unchanged in scope)
    still runs end to end after adding the _keyword_matches import."""
    ndb = MagicMock()
    ndb.get_session.return_value = {"topic": "dense retrieval"}
    ndb.get_papers.return_value = [{"title": f"Paper {i}", "year": 2020 + i} for i in range(30)]
    ndb.get_hypotheses.return_value = []
    ndb.get_session_experiment_code.return_value = [
        {"file_path": "train.py", "file_content": "recall_at_10 = 0.8\nbm25_baseline=True\nsbert=True\ndpr=True"},
    ]

    api = MagicMock()
    api.generate_structured.side_effect = RuntimeError("no LLM in this test")

    agent = QualityReviewAgent(api_model=api, note_db=ndb)
    report = agent.review("session-1")

    assert report.session_id == "session-1"
    assert 0 <= report.score <= 100
    assert report.gate in ("pass", "warn", "fail")
