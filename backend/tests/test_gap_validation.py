"""
Regression tests for the gap-validation gate (agents/gap_analysis.py).

Background: a 2026-09-12 audit found the agent's gap analysis confidently
claimed things like "no comparisons between Transformers and RNNs exist in
RL" when that had been directly contradicted by published work (Ni et al.
2022, POPGym 2023) for years. validate_gap_report() exists to catch exactly
this before a gap reaches the user or the research-question prompt.

A second 2026-09-12 test session then found validate_gap_report() itself
fabricating evidence: it cited paper titles as containing phrases ("the
title mentions developing countries", "the title mentions a non-linear
relationship") that were not actually in those titles — hallucination in
the exact layer whose job is to prevent hallucination, produced by the
local llama3.1:8b fallback. _verify_evidence_spans() now requires a
verbatim quoted span and checks it programmatically against the real
title text, which is what most of the tests below pin.

No real API/network calls — APIModel and tools.sources.search_all are mocked.
"""
import json
from unittest.mock import patch, MagicMock

from agents.gap_analysis import GapAnalysisAgent, _echoes_input

FAKE_GAP_REPORT = (
    "**Research Gap Report**\n"
    "1. Missing Baselines: no similar comparisons are made between Transformers "
    "and RNNs in reinforcement learning.\n"
    "2. Scalability: memory requirements in resource-constrained edge devices "
    "are largely unexplored.\n"
)

EXTRACT_RESPONSE = json.dumps([
    {"claim": "No comparisons between Transformers and RNNs exist in RL.",
     "search_query": "transformer recurrent comparison reinforcement learning POMDP",
     "key_terms": ["RL"]},
    {"claim": "Transformer memory requirements on edge devices are unexplored.",
     "search_query": "edge device transformer memory efficient reinforcement learning",
     "key_terms": ["edge devices"]},
])

VERIFY_RESPONSE = json.dumps([
    {"claim": "No comparisons between Transformers and RNNs exist in RL.",
     "verdict": "LIKELY_ADDRESSED",
     "evidence_arxiv_id": "2110.05038",
     "evidence_span": "Recurrent Model-Free RL Can Be a Strong Baseline",
     "reasoning": "Directly benchmarks recurrent vs specialized/transformer-style methods."},
    {"claim": "Transformer memory requirements on edge devices are unexplored.",
     "verdict": "CONFIRMED_GAP",
     "evidence_arxiv_id": "",
     "evidence_span": "",
     "reasoning": "No relevant results found."},
])

# Same shape as tonight's real fabrication: verdict LIKELY_ADDRESSED with an
# evidence_span that does not appear anywhere in the candidate paper's title.
FABRICATED_VERIFY_RESPONSE = json.dumps([
    {"claim": "No comparisons between Transformers and RNNs exist in RL.",
     "verdict": "LIKELY_ADDRESSED",
     "evidence_arxiv_id": "2110.05038",
     "evidence_span": "developing countries fuel economy",  # not in the title at all
     "reasoning": "The paper's title mentions developing countries."},
    {"claim": "Transformer memory requirements on edge devices are unexplored.",
     "verdict": "CONFIRMED_GAP",
     "evidence_arxiv_id": "",
     "evidence_span": "",
     "reasoning": "No relevant results found."},
])

FAKE_SEARCH_RESULTS = {
    "transformer recurrent comparison reinforcement learning POMDP": [
        MagicMock(arxiv_id="2110.05038",
                  title="Recurrent Model-Free RL Can Be a Strong Baseline for Many POMDPs",
                  year=2022, abstract=""),
    ],
    "edge device transformer memory efficient reinforcement learning": [],
}


def _fake_generate_structured(prompt, system, task_type):
    if "Extract every claim" in prompt:
        return EXTRACT_RESPONSE
    return VERIFY_RESPONSE


def _fake_search(query, limit=5, sources=None):
    return FAKE_SEARCH_RESULTS.get(query, []), {}


def test_happy_path_flags_the_actual_false_gap_found_in_the_audit():
    """Regression pin for the exact false claim the 2026-09-12 audit found."""
    api = MagicMock()
    api.generate_structured.side_effect = _fake_generate_structured
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    with patch("tools.sources.search_all", _fake_search):
        annotated, findings = agent.validate_gap_report(
            "transformer vs RNN in RL", FAKE_GAP_REPORT, "sess-1"
        )

    assert len(findings) == 2
    assert findings[0].verdict == "LIKELY_ADDRESSED"
    assert findings[0].evidence_verified is True
    assert "2110.05038" in findings[0].evidence
    assert findings[1].verdict == "CONFIRMED_GAP"
    assert "## Gap Validation" in annotated
    assert FAKE_GAP_REPORT.strip() in annotated  # original report text preserved


def test_fabricated_evidence_span_is_caught_and_downgraded():
    """
    Regression pin for the 2026-09-12 fabrication incident: a verdict of
    LIKELY_ADDRESSED whose evidence_span does not actually appear in the
    cited paper's title must be mechanically downgraded to UNCERTAIN,
    regardless of how confident the model's own reasoning sounds.
    """
    api = MagicMock()

    def side_effect(prompt, system, task_type):
        if "Extract every claim" in prompt:
            return EXTRACT_RESPONSE
        return FABRICATED_VERIFY_RESPONSE

    api.generate_structured.side_effect = side_effect
    note_db = MagicMock()
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)

    with patch("tools.sources.search_all", _fake_search):
        annotated, findings = agent.validate_gap_report("topic", FAKE_GAP_REPORT, "sess-1")

    fabricated = findings[0]
    assert fabricated.verdict == "UNCERTAIN"  # downgraded from LIKELY_ADDRESSED
    assert fabricated.evidence_verified is False
    assert "downgraded" in fabricated.checks

    # The downgrade must itself be recorded as a critical degradation.
    degradation_calls = [
        call for call in note_db.save_degradation.call_args_list
        if call.args[1:4] == (3, "gap_validation", "critical")
    ]
    assert degradation_calls, note_db.save_degradation.call_args_list
    assert "Fabricated evidence" in degradation_calls[0].args[4]


def test_sources_skipped_during_validation_are_recorded_once():
    """A blocked or unconfigured source must show up as a degradation, not vanish."""
    api = MagicMock()
    api.generate_structured.side_effect = _fake_generate_structured
    note_db = MagicMock()
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)

    def search_with_blocked_arxiv(query, limit=5, sources=None):
        return FAKE_SEARCH_RESULTS.get(query, []), {"arxiv": "arxiv is blocked until 2026-09-20"}

    with patch("tools.sources.search_all", search_with_blocked_arxiv):
        agent.validate_gap_report("topic", FAKE_GAP_REPORT, "sess-1")

    arxiv_records = [
        c for c in note_db.save_degradation.call_args_list
        if c.args[1:3] == (3, "source:arxiv")
    ]
    assert len(arxiv_records) == 1  # two claims searched, recorded once


def test_no_checkable_claims_leaves_report_unchanged():
    api = MagicMock()
    api.generate_structured.return_value = "[]"
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    annotated, findings = agent.validate_gap_report("topic", FAKE_GAP_REPORT, "sess-1")

    assert findings == []
    assert annotated == FAKE_GAP_REPORT


def test_malformed_extraction_json_degrades_without_crashing():
    api = MagicMock()
    api.generate_structured.return_value = "not json at all {{{"
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    annotated, findings = agent.validate_gap_report("topic", FAKE_GAP_REPORT, "sess-1")

    assert findings == []
    assert annotated == FAKE_GAP_REPORT  # must not block Phase 3


def test_verification_call_failure_degrades_to_uncertain_not_a_crash():
    api = MagicMock()

    def side_effect(prompt, system, task_type):
        if "Extract every claim" in prompt:
            return EXTRACT_RESPONSE
        raise RuntimeError("simulated API failure")

    api.generate_structured.side_effect = side_effect
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    with patch("tools.sources.search_all", _fake_search):
        annotated, findings = agent.validate_gap_report("topic", FAKE_GAP_REPORT, "sess-1")

    assert len(findings) == 2
    assert all(f.verdict == "UNCERTAIN" for f in findings)
    assert "## Gap Validation" in annotated


def test_markdown_fenced_json_still_parses():
    """Models sometimes wrap JSON in ```json fences despite instructions not to."""
    api = MagicMock()

    def side_effect(prompt, system, task_type):
        body = EXTRACT_RESPONSE if "Extract every claim" in prompt else VERIFY_RESPONSE
        return f"```json\n{body}\n```"

    api.generate_structured.side_effect = side_effect
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    with patch("tools.sources.search_all", _fake_search):
        _, findings = agent.validate_gap_report("topic", FAKE_GAP_REPORT, "sess-1")

    assert len(findings) == 2


# ---------------------------------------------------------------------------
# Collection-health injection into the gap-analysis prompt
# ---------------------------------------------------------------------------

def test_gap_analysis_prompt_forbids_no_study_language_when_collection_degraded():
    """
    Regression pin: a 2026-09-12 test session found the gap report writing
    "No study focuses on X" seven times despite the paper collection being
    arXiv-only and having 0 canon-seeded papers — a degradation the system
    itself had recorded but never surfaced to the LLM writing the report.
    """
    api = MagicMock()
    api.generate.return_value = "a gap report"
    note_db = MagicMock()
    note_db.get_degradations.return_value = [
        {"severity": "critical", "component": "canon_seeding",
         "message": "Semantic Scholar returned 0 papers."},
    ]
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)

    agent._analyse_gaps("topic", "lit summary", 20, "sess-1")

    prompt_used = api.generate.call_args.kwargs["prompt"]
    assert "canon_seeding" in prompt_used
    assert 'Never write "no study has"' in prompt_used


def test_gap_analysis_prompt_reports_healthy_collection_when_no_degradations():
    api = MagicMock()
    api.generate.return_value = "a gap report"
    note_db = MagicMock()
    note_db.get_degradations.return_value = []
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)

    agent._analyse_gaps("topic", "lit summary", 20, "sess-1")

    prompt_used = api.generate.call_args.kwargs["prompt"]
    assert "No degradations recorded." in prompt_used


# ---------------------------------------------------------------------------
# UNCERTAIN must not be usable as novelty grounding
# ---------------------------------------------------------------------------

def test_question_prompt_distinguishes_uncertain_from_confirmed_gap():
    """
    Regression pin: the old prompt said "Prefer gaps marked CONFIRMED_GAP or
    UNCERTAIN", treating a failed verification as equally good grounding as
    a confirmed one. A 2026-09-12 test session found this producing a
    research question whose sole novelty justification was "marked as
    UNCERTAIN" — promoting a verification failure to a confirmed gap.
    """
    api = MagicMock()
    api.generate.return_value = "RQ 1: something\n- Feasibility: yes\n- Novelty: n/a\n- Effort: Low"
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    agent._generate_questions("some topic", "gap analysis text")

    prompt_used = api.generate.call_args.kwargs["prompt"]
    assert "UNCERTAIN" in prompt_used
    assert "we don't know" in prompt_used or "we don" in prompt_used
    assert "not evidence of novelty" in prompt_used.lower()


# ---------------------------------------------------------------------------
# Input-echo detection
# ---------------------------------------------------------------------------

def test_echoes_input_detects_verbatim_copy():
    goals = (
        "Answer one question: which country-level conditions distinguish places "
        "where clean fuel reliance has kept rising from places where it has "
        "stalled or reversed."
    )
    # Same sentence, verbatim — this is what RQ1 looked like in the real session.
    assert _echoes_input(goals, goals) is True


def test_echoes_input_allows_a_genuinely_different_question():
    goals = "Answer one question: which country-level conditions distinguish trajectories."
    rq = "Does household size moderate the relationship between income and stove upgrades?"
    assert _echoes_input(rq, goals) is False


def test_generated_questions_are_flagged_when_they_echo_the_topic():
    api = MagicMock()
    topic = "Sustained adoption and fuel stacking after clean cooking transitions"
    # The model just echoes the topic text back as RQ 1.
    api.generate.return_value = f"RQ 1: {topic}\n- Feasibility: yes\n- Novelty: n/a\n- Effort: Low"
    note_db = MagicMock()
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)
    agent._ensure_deg("sess-1")  # normally done by _analyse_gaps/validate_gap_report first

    questions = agent._generate_questions(topic, "gap analysis text")

    assert questions[0].echoes_input is True
    note_db.save_degradation.assert_called()


# ---------------------------------------------------------------------------
# Echo detection on the real 2026-09-13 questions (goals-based, 3-gram)
# ---------------------------------------------------------------------------

REAL_GOALS = (
    "Answer one question: which country-level conditions distinguish places where clean "
    "fuel reliance has kept rising from places where it has stalled or reversed, and does "
    "that pattern differ between urban and rural populations within the same country."
)
REAL_RQ1 = (
    "What country-level factors distinguish places where the proportion of the population "
    "relying on clean fuels has continued to rise from places where it has stalled or "
    "reversed, and do these factors differ between urban and rural populations within the "
    "same country?"
)
REAL_RQ3 = (
    "What is the relationship between the adoption of clean cooking fuels and the use of "
    "alternative fuels (e.g. charcoal, wood) in rural settings, and how does this "
    "relationship vary across different countries and regions?"
)


def test_close_paraphrase_of_goals_is_flagged():
    assert _echoes_input(REAL_RQ1, REAL_GOALS) is True


def test_on_topic_question_is_not_flagged_just_for_sharing_vocabulary():
    """Regression pin: the old whole-brief word-ratio check flagged this (false positive)."""
    assert _echoes_input(REAL_RQ3, REAL_GOALS) is False


def test_generate_questions_compares_against_goals_when_given():
    api = MagicMock()
    long_brief = REAL_GOALS + " " + REAL_RQ3  # brief happens to contain RQ3's wording
    api.generate.return_value = f"RQ 1: {REAL_RQ3}\n- Feasibility: yes\n- Novelty: n/a\n- Effort: Low"
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    questions = agent._generate_questions(long_brief, "gap analysis", goals=REAL_GOALS)

    assert questions[0].echoes_input is False


# ---------------------------------------------------------------------------
# Novelty labels checked against the actual validation verdicts
# ---------------------------------------------------------------------------

def _finding(claim, verdict):
    from agents.gap_analysis import GapValidationFinding
    return GapValidationFinding(claim=claim, search_query="q", verdict=verdict)


REAL_FINDINGS = [
    _finding("Fuel stacking remains poorly understood and its impact is not well quantified.", "LIKELY_ADDRESSED"),
    _finding("Ablation studies examining the effect of removing a specific variable or intervention are rare.", "UNCERTAIN"),
    _finding("Baseline studies quantifying the current state of household air pollution and clean cooking fuel use are lacking.", "LIKELY_ADDRESSED"),
]


def _rq(novelty):
    from agents.gap_analysis import ResearchQuestion
    return ResearchQuestion(index=1, text="q", novelty_notes=novelty)


def test_novelty_label_contradicting_validation_is_corrected():
    """Regression pin for the 2026-09-13 run's RQ1."""
    from agents.gap_analysis import _verify_novelty_labels
    rq = _rq("Built on CONFIRMED_GAP (fuel stacking remains poorly understood and its impact is not well quantified).")

    corrected = _verify_novelty_labels([rq], REAL_FINDINGS)

    assert corrected
    assert rq.novelty_notes.startswith("[Label corrected: cited CONFIRMED_GAP, but validation result is LIKELY_ADDRESSED]")


def test_novelty_label_matching_validation_is_left_alone():
    from agents.gap_analysis import _verify_novelty_labels
    note = "Built on LIKELY_ADDRESSED (baseline studies quantifying the current state of household air pollution and clean cooking fuel use are lacking)."
    rq = _rq(note)

    assert _verify_novelty_labels([rq], REAL_FINDINGS) == []
    assert rq.novelty_notes == note


def test_citing_a_verdict_no_claim_has_is_corrected_even_without_a_claim_match():
    from agents.gap_analysis import _verify_novelty_labels
    rq = _rq("Built on CONFIRMED_GAP (something entirely different about stove supply chains).")

    corrected = _verify_novelty_labels([rq], REAL_FINDINGS)

    assert corrected and "no claim with that verdict" in rq.novelty_notes


def test_novelty_mismatch_is_recorded_as_degradation():
    api = MagicMock()
    api.generate.return_value = (
        "RQ 1: some question\n- Feasibility: yes\n"
        "- Novelty: Built on CONFIRMED_GAP (fuel stacking remains poorly understood and its impact is not well quantified)\n"
        "- Effort: Low"
    )
    note_db = MagicMock()
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)
    agent._ensure_deg("sess-1")

    agent._generate_questions("topic", "gap analysis", REAL_FINDINGS, goals=REAL_GOALS)

    assert any(c.args[1:3] == (3, "novelty_label") for c in note_db.save_degradation.call_args_list)
