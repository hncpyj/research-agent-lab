"""
The ML-path review reads the code, not the text of the code.

2026-09-20 backlog: domain alignment, baselines and statistical rigour were
decided by substring search, so a word in a comment counted as evidence and
the same thing written differently did not.
"""
from agents.code_facts import collect
from agents.quality_review import QualityReviewAgent


def _agent():
    return object.__new__(QualityReviewAgent)


RETRIEVAL = "dense retrieval for scientific search"


def test_a_comment_is_not_evidence_that_the_code_does_it():
    facts = collect({"train.py": "# TODO: use gymnasium and set a seed\nx = 1\n"})
    assert facts.imports_any(["gymnasium"]) == []
    assert not facts.mentions("manual_seed")


def test_an_import_is_found_even_when_aliased():
    facts = collect({"train.py": "import gymnasium as gym\nfrom stable_baselines3 import PPO\n"})
    assert facts.imports_any(["gymnasium"]) == ["gymnasium"]
    assert facts.imports_any(["stable_baselines3.PPO"]) == ["stable_baselines3.PPO"]


def test_a_file_that_does_not_parse_is_reported_not_guessed_at():
    facts = collect({"train.py": "def broken(:\n"})
    assert facts.unparsed == ["train.py"]

    findings = _agent()._check_code_domain_alignment(RETRIEVAL, {"train.py": "def broken(:\n"})
    assert findings[0].criterion == "code_not_readable" and findings[0].level == "warn"


def test_rl_code_in_a_retrieval_project_still_fails():
    code = {"train.py": "import gymnasium\n\ndef run():\n    env = gymnasium.make('CartPole-v1')\n"}
    findings = _agent()._check_code_domain_alignment(RETRIEVAL, code)
    assert any(f.level == "fail" and f.criterion == "code_domain_alignment" for f in findings)


def test_a_mention_in_a_docstring_no_longer_fails_the_project():
    code = {"train.py": '"""Unlike gymnasium-based RL work, this indexes with faiss."""\n'
                        "import faiss\n\n"
                        "def search(index, q):\n"
                        "    return index.search(q, 10)  # recall, mrr, ndcg computed elsewhere\n"}
    findings = _agent()._check_code_domain_alignment(RETRIEVAL, code)
    assert not any(f.level == "fail" for f in findings)


def test_seeds_and_tests_count_when_they_are_actually_called():
    code = {"eval.py": "import numpy as np\nfrom scipy import stats\n\n"
                       "def main():\n"
                       "    rng = np.random.default_rng(0)\n"
                       "    a, b = rng.normal(size=10), rng.normal(size=10)\n"
                       "    stats.ttest_rel(a, b)\n"
                       "    print(a.std())\n"}
    findings = _agent()._check_statistical_rigour(code, {})
    assert [f.level for f in findings] == ["pass"]


def test_the_word_seed_in_a_name_is_not_seed_management():
    code = {"eval.py": "seedless_results = []\n\ndef main():\n    print('no seeding here')\n"}
    findings = _agent()._check_statistical_rigour(code, {})
    assert findings[0].level == "fail"
    assert "random seed" in findings[0].detail
