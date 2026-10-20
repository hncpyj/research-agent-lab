"""
Regression tests for the baseline-literature cross-check (item F of the roadmap).

Background: earlier roadmap drafts of item F proposed just checking that a
generated baseline "isn't degenerate" (not NaN/zero/random-chance). The user
pushed back: real research labs compare against a SPECIFIC published number,
not just a vague sanity range — and skipping that comparison would be LESS
rigorous than standard practice, not more honest. This check does the
stronger version: extract a specific, quoted number from the literature and
compare it to what the generated baseline actually scored. Both extraction
steps require literal evidence (a JSON path / a quoted text span) rather than
a bare LLM assertion, so this can't become a new instance of the exact
fabricated-confidence problem the whole audit is about.
"""
import json
from unittest.mock import MagicMock

from agents.quality_review import QualityReviewAgent


def _agent():
    return QualityReviewAgent(api_model=MagicMock(), note_db=MagicMock())


def _hypotheses(baseline_desc="LSTM baseline", metrics=("accuracy",)):
    return [{
        "status": "code_generated",
        "experiment_design": {"baseline": baseline_desc, "metrics": list(metrics)},
    }]


def _papers():
    return [{
        "title": "Recurrent Model-Free RL Can Be a Strong Baseline for Many POMDPs",
        "year": 2022,
        "abstract": "Our LSTM baseline achieves 0.82 accuracy on the benchmark suite, "
                    "matching or exceeding specialized transformer-based methods.",
    }]


def test_matches_within_tolerance_is_a_pass():
    agent = _agent()
    agent._api.generate_structured.side_effect = [
        json.dumps({"found": True, "json_path": "baseline.accuracy", "value": 0.80, "metric_name": "accuracy"}),
        json.dumps({"found": True, "source_title": "Recurrent Model-Free RL...", "quote": "0.82 accuracy",
                     "value": 0.82, "metric_name": "accuracy"}),
    ]

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"baseline": {"accuracy": 0.80}},
    )

    assert len(findings) == 1
    assert findings[0].level == "pass"
    assert findings[0].criterion == "baseline_literature_match"
    assert "0.8" in findings[0].detail


def test_large_divergence_is_a_fail_with_clear_warning_language():
    agent = _agent()
    agent._api.generate_structured.side_effect = [
        json.dumps({"found": True, "json_path": "baseline.accuracy", "value": 0.20, "metric_name": "accuracy"}),
        json.dumps({"found": True, "source_title": "Recurrent Model-Free RL...", "quote": "0.82 accuracy",
                     "value": 0.82, "metric_name": "accuracy"}),
    ]

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"baseline": {"accuracy": 0.20}},
    )

    assert len(findings) == 1
    assert findings[0].level == "fail"
    assert "not trustworthy" in findings[0].detail
    assert "0.2" in findings[0].detail and "0.82" in findings[0].detail


def test_no_eval_data_degrades_to_warn_without_crashing():
    agent = _agent()
    findings = agent._check_baseline_literature_match("topic", _hypotheses(), _papers(), {})
    assert len(findings) == 1
    assert findings[0].level == "warn"
    agent._api.generate_structured.assert_not_called()  # never even tries without eval data


def test_baseline_not_found_in_eval_data_is_a_warn_not_a_fail():
    agent = _agent()
    agent._api.generate_structured.return_value = json.dumps({"found": False})

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"some_metric": 0.5},
    )

    assert len(findings) == 1
    assert findings[0].level == "warn"
    assert "distinct baseline" in findings[0].title.lower() or "No Distinct Baseline" in findings[0].title


def test_no_literature_number_found_is_a_warn_not_a_fail():
    """Absence of a comparable published number is not evidence the baseline
    is wrong — must not be scored as a failure."""
    agent = _agent()
    agent._api.generate_structured.side_effect = [
        json.dumps({"found": True, "json_path": "baseline.accuracy", "value": 0.55, "metric_name": "accuracy"}),
        json.dumps({"found": False}),
    ]

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"baseline": {"accuracy": 0.55}},
    )

    assert len(findings) == 1
    assert findings[0].level == "warn"
    assert "No Comparable Literature Number" in findings[0].title


def test_extraction_call_failure_degrades_gracefully():
    agent = _agent()
    agent._api.generate_structured.side_effect = RuntimeError("simulated API failure")

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"baseline": {"accuracy": 0.5}},
    )

    assert len(findings) == 1
    assert findings[0].level == "warn"


def test_malformed_json_from_llm_degrades_gracefully():
    agent = _agent()
    agent._api.generate_structured.return_value = "not json at all {{{"

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"baseline": {"accuracy": 0.5}},
    )

    assert len(findings) == 1
    assert findings[0].level == "warn"


def test_markdown_fenced_json_still_parses():
    agent = _agent()
    agent._api.generate_structured.side_effect = [
        "```json\n" + json.dumps({"found": True, "json_path": "x", "value": 0.5, "metric_name": "accuracy"}) + "\n```",
        "```json\n" + json.dumps({"found": True, "source_title": "P", "quote": "0.5 accuracy",
                                    "value": 0.5, "metric_name": "accuracy"}) + "\n```",
    ]

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"baseline": {"accuracy": 0.5}},
    )

    assert findings[0].level == "pass"


def test_never_fabricates_a_number_when_llm_honestly_says_not_found():
    """Both prompts explicitly instruct the model to prefer an honest
    found=false over a plausible-sounding guess. Pin that the code respects
    that signal rather than treating any response as a match."""
    agent = _agent()
    agent._api.generate_structured.side_effect = [
        json.dumps({"found": False, "json_path": None, "value": None, "metric_name": None}),
    ]

    findings = agent._check_baseline_literature_match(
        "topic", _hypotheses(), _papers(), {"some_metric": 0.5},
    )

    assert findings[0].level == "warn"
    assert findings[0].criterion == "baseline_literature_match"
