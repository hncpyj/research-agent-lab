"""
The evidence trail itself, checked like anything else.

If the record-keeping is unreliable then every number that comes out of it is
unreliable too, and in a way that is very hard to notice later. So: records are
never overwritten, the benchmark is well formed and its invariants are real
claims about the current system, aggregates carry numerators and denominators,
and a recovered failure is still counted as a failure.

Layer 1 (deterministic software regression) and Layer 2 (scientific invariants).
No model is called here.
"""
import json
from pathlib import Path

import pytest

from tools import benchmark_runner, research_log


@pytest.fixture
def logs(tmp_path, monkeypatch):
    """Point the record writer at a temporary tree."""
    monkeypatch.setattr(research_log, "ROOT", tmp_path)
    monkeypatch.setattr(research_log, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(research_log, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(research_log, "JSONL", tmp_path / "runs.jsonl")
    return tmp_path


def _record(**overrides) -> research_log.RunRecord:
    fields = dict(
        summary="test_run", title="A test run", question="Does the writer work?",
        change="nothing", prediction="it writes three files", baseline="none",
        procedure="call write()", classification="C", evaluation_kind="DEVELOPMENT",
        decision="KEEP", next_test="none")
    fields.update(overrides)
    return research_log.RunRecord(**fields)


# --- the record ---------------------------------------------------------------------

def test_a_run_is_written_three_ways(logs):
    markdown, record = _record().write()

    assert markdown.exists() and record.exists()
    assert (logs / "runs.jsonl").exists()
    body = markdown.read_text(encoding="utf-8")
    for heading in ("## Question", "## Change", "## Prediction", "## Baseline",
                    "## Test Procedure", "## Quantitative Results", "## Failures",
                    "## Comparison to Baseline", "## Interpretation",
                    "## Threats / Confounds", "## Decision", "## Next Test",
                    "## Paper Relevance"):
        assert heading in body, heading


def test_a_second_run_in_the_same_minute_does_not_overwrite_the_first(logs):
    first_md, first_json = _record().write()
    second_md, second_json = _record().write()

    assert first_md != second_md and first_json != second_json
    assert first_md.exists() and second_md.exists()
    assert len(list((logs / "runs").glob("*.md"))) == 2
    assert len((logs / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 2


def test_the_record_says_which_code_produced_it(logs):
    _, record = _record().write()
    payload = json.loads(record.read_text(encoding="utf-8"))

    assert payload["schema"] == "run_record_v1"
    assert payload["git_commit"] and payload["git_commit"] != ""
    assert isinstance(payload["working_tree_dirty"], bool)
    assert payload["environment"]["python"]


def test_a_recovered_failure_is_still_counted(logs):
    run = _record(failure_events=[
        {"labels": ["MALFORMED_GENERATION"], "detail": "missing placeholder",
         "recovered": True, "detected_at": "generation/validation"}])
    _, record = run.write()

    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["failure_taxonomy_counts"] == {"MALFORMED_GENERATION": 1}


def test_an_unclassified_run_is_refused():
    """A record without a research classification is not a research record."""
    with pytest.raises(ValueError, match="classification"):
        _record(classification="X")
    with pytest.raises(ValueError, match="evaluation_kind"):
        _record(evaluation_kind="MAYBE")
    with pytest.raises(ValueError, match="three words"):
        _record(summary="far_too_many_words_here")


# --- the benchmark ------------------------------------------------------------------

def test_the_benchmark_is_well_formed():
    data = research_log.benchmark("v1")

    assert data["benchmark_version"] == "v1" and data["frozen_at"]
    assert data["cases"], "a benchmark with no cases measures nothing"
    for case in data["cases"]:
        for field in ("benchmark_id", "research_question", "hypothesis", "gold_protocol",
                      "mechanical_invariants", "known_positive_failures",
                      "expected_execution_tier"):
            assert case.get(field), f"{case.get('benchmark_id')} has no {field}"
        assert len(case["known_positive_failures"]) >= 5, (
            "the positive failure cases are the safety regression benchmark; "
            "they should grow, never shrink")


def test_every_positive_failure_case_carries_taxonomy_labels():
    known = {label for section in ("Scientific", "Generation", "Software", "Repair", "not defects")
             for label in []}                     # labels live in taxonomy.md, read below
    taxonomy = (Path(research_log.ROOT) / "taxonomy.md").read_text(encoding="utf-8")
    for case in research_log.benchmark("v1")["cases"]:
        for failure in case["known_positive_failures"]:
            assert failure["taxonomy"], failure["id"]
            for label in failure["taxonomy"]:
                assert f"`{label}`" in taxonomy, f"{label} is not in the taxonomy"


def test_the_gold_protocol_matches_what_the_system_builds():
    """
    The benchmark's expected protocol and the protocol the system produces must
    agree, or the benchmark is measuring a design nobody implements.
    """
    from agents.experiment_agent import build_spec

    case = research_log.benchmark("v1")["cases"][0]
    gold = case["gold_protocol"]
    built = build_spec(case["hypothesis"])

    assert built.study_type.value == gold["study_type"]
    assert built.scaffold_id == case["expected_scaffold_id"]
    assert built.requires_training == gold["requires_training"]
    assert built.dataset_policy.value == gold["dataset_policy"]
    assert list(built.conditions) == gold["conditions"]
    assert built.primary_metric == gold["primary_metric"]
    assert list(built.secondary_metrics) == gold["secondary_metrics"]
    assert list(built.independent_variables) == gold["independent_variables"]
    assert list(built.dependent_variables) == gold["dependent_variables"]
    for name in gold["held_constant_must_include"]:
        assert name in built.held_constant
    assert [o.path for o in built.required_outputs] == gold["required_outputs"]


def test_the_expected_tier_is_the_tier_the_manifest_chooses():
    from agents import build_manifest as manifest_module
    from agents.experiment_agent import build_spec

    case = research_log.benchmark("v1")["cases"][0]
    manifest = manifest_module.plan(build_spec(case["hypothesis"]).approve().freeze())
    assert manifest.execution_tier.value == case["expected_execution_tier"]


# --- the aggregate ------------------------------------------------------------------

def _attempt(**overrides) -> benchmark_runner.Attempt:
    fields = dict(attempt=1, seed=1, status="verified_ready", review_verdict="PASS",
                  intent_fidelity="PASS", conformance="PASS", preflight="PASS",
                  runtime="PASS", results_conformance="PASS", first_pass_valid=True,
                  generation_calls=9)
    fields.update(overrides)
    return benchmark_runner.Attempt(**fields)


def test_every_rate_carries_its_denominator():
    metrics = benchmark_runner.aggregate([_attempt(), _attempt(attempt=2)])

    assert metrics["attempts"] == 2
    for key, value in metrics.items():
        if key.endswith(("_pass", "completion", "halt", "failure", "block", "valid",
                         "recovered")):
            assert "/" in str(value), f"{key} is {value}: a rate without a denominator"


def test_a_run_that_executed_but_failed_conformance_is_a_silent_failure():
    """The metric the whole direction is about: it ran, and it was wrong."""
    metrics = benchmark_runner.aggregate([
        _attempt(runtime="PASS", results_conformance="FAIL")])
    assert metrics["silent_scientific_failure"] == "1/1"
    assert metrics["valid_completion"] == "0/1"


def test_a_halt_is_not_counted_as_a_completion():
    metrics = benchmark_runner.aggregate([
        _attempt(status="scientific_verification_failed", conformance="FAIL",
                 runtime="", results_conformance="")])
    assert metrics["safe_halt"] == "1/1"
    assert metrics["valid_completion"] == "0/1"
    assert metrics["silent_scientific_failure"] == "0/1"


def test_recovered_failures_are_counted_apart_from_real_ones():
    attempt = _attempt(failures=[
        {"labels": ["MALFORMED_GENERATION"], "recovered": True, "detail": "retried"},
        {"labels": ["RUNTIME_ERROR"], "recovered": False, "detail": "crashed"}])
    metrics = benchmark_runner.aggregate([attempt])

    assert metrics["failure_taxonomy_counts"] == {"RUNTIME_ERROR": 1}
    assert metrics["recovered_failure_counts"] == {"MALFORMED_GENERATION": 1}


def test_raw_attempts_are_kept_so_aggregates_can_be_recomputed(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark_runner, "RAW_DIR", tmp_path)
    attempts = [_attempt(), _attempt(attempt=2, status="design_rejected")]

    path = benchmark_runner.save_raw(attempts, "check")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(lines) == 2                    # including the rejected one
    assert benchmark_runner.aggregate(
        [benchmark_runner.Attempt(**line) for line in lines])["attempts"] == 2
