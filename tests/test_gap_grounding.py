"""
Tests for grounding gap analysis in the collected papers (agents/gap_analysis.py).

Background (2026-09-13 run e794e0af): with a collection that was 20/20 on
topic, the gap report still called fuel stacking "poorly understood" while
six collected papers were about fuel stacking, and gap validation cited an
injera-stove combustion experiment, a hypertension study and a
cardiovascular study as evidence for claims about cooking-fuel
interventions. Those citations passed the old check because the quoted words
really were in the titles; the reasoning around them was invented. The cases
below are taken from that run.
"""
import json
from unittest.mock import MagicMock, patch

from agents.gap_analysis import (
    GapAnalysisAgent,
    GapValidationFinding,
    _find_candidate,
    _papers_containing,
)

EVERYBODY_STACKS = {
    "arxiv_id": "epmc:MED:32476710",
    "title": "Everybody Stacks: Lessons from household energy case studies to inform design principles for clean energy transitions",
    "abstract": "Fuel stacking, the use of multiple fuels, is the norm in households transitioning to clean cooking.",
    "findings": "", "limitation": "", "future_work": "",
}
RURAL_LPG = {
    "arxiv_id": "epmc:MED:32581420",
    "title": "LPG as a Clean Cooking Fuel: Adoption, Use, and Impact in Rural India",
    "abstract": "Uptake of LPG among rural households after subsidy programmes.",
    "findings": "", "limitation": "", "future_work": "",
}


def _note_db(papers=(), constraints=""):
    db = MagicMock()
    db.get_papers.return_value = list(papers)
    db.get_session.return_value = {"constraints": constraints, "goals": "", "background": ""}
    db.get_degradations.return_value = []
    return db


# --- collection-first check -------------------------------------------------------------

def test_key_term_match_is_stemmed_and_requires_every_term():
    assert _papers_containing(["fuel stacking"], [EVERYBODY_STACKS]) == [EVERYBODY_STACKS]
    assert _papers_containing(["fuel stacking", "rural"], [EVERYBODY_STACKS]) == []
    assert _papers_containing([], [EVERYBODY_STACKS]) == []


def test_claim_contradicted_by_the_collection_is_marked_and_not_searched_externally():
    """Regression pin: 'fuel stacking remains poorly understood' with stacking papers in hand."""
    extract = json.dumps([{
        "claim": "Fuel stacking in households remains poorly understood.",
        "search_query": "fuel stacking household energy",
        "key_terms": ["fuel stacking", "households"],
    }])
    api = MagicMock()
    api.generate_structured.return_value = extract
    api.generate.return_value = (
        "ANSWERS: yes\nQUOTE: Fuel stacking, the use of multiple fuels, is the norm in households "
        "transitioning to clean cooking.")
    agent = GapAnalysisAgent(api_model=api, note_db=_note_db([EVERYBODY_STACKS]))

    with patch("tools.sources.search_all") as search:
        _, findings = agent.validate_gap_report("topic", "report", "sess-1")

    assert findings[0].verdict == "CONTRADICTED_BY_COLLECTION"
    assert "Everybody Stacks" in findings[0].evidence
    search.assert_not_called()


def test_key_terms_not_found_in_the_claim_are_discarded():
    extract = json.dumps([{
        "claim": "Few studies examine rural adoption.",
        "search_query": "rural adoption clean cooking",
        "key_terms": ["rural", "fuel stacking"],  # "fuel stacking" is not in the claim
    }])
    api = MagicMock()
    api.generate_structured.return_value = extract
    agent = GapAnalysisAgent(api_model=api, note_db=_note_db())

    claims = agent._extract_claims("topic", "report")

    assert claims[0]["key_terms"] == ["rural"]


# --- citation checks --------------------------------------------------------------

def _finding(evidence_id, span, candidates, key_terms):
    return GapValidationFinding(
        claim="The effectiveness of clean cooking fuel interventions in rural settings is not well understood.",
        search_query="q", verdict="LIKELY_ADDRESSED", papers_found=candidates,
        evidence_span=span, evidence_id=evidence_id, key_terms=key_terms,
    )


def test_cited_id_without_source_prefix_still_matches():
    cands = [{"arxiv_id": "doi:10.2139/ssrn.6795470", "title": "A stacking framework"}]
    assert _find_candidate("10.2139/ssrn.6795470", cands) is cands[0]
    assert _find_candidate("[MED:32476710]", [EVERYBODY_STACKS]) is EVERYBODY_STACKS


def test_citation_with_real_span_but_no_key_term_is_downgraded_as_irrelevant():
    """Regression pin: the Peruvian hypertension study cited for rural intervention effectiveness."""
    peru = {"arxiv_id": "epmc:MED:42652981",
            "title": "Biomass Cooking Fuel Use and Screen-Detected Hypertension Among Peruvian Women",
            "abstract": "Cross-sectional survey of blood pressure."}
    note_db = _note_db()
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=note_db)
    agent._ensure_deg("sess-1")
    f = _finding("epmc:MED:42652981", "Biomass Cooking Fuel Use", [peru], ["interventions", "rural"])

    agent._verify_evidence_spans([f])

    assert f.verdict == "UNCERTAIN"
    assert "none of the claim's key terms" in f.checks
    assert any(c.args[1:4] == (3, "gap_validation", "warn") for c in note_db.save_degradation.call_args_list)


def test_citation_well_below_the_best_candidate_is_downgraded():
    best = {"arxiv_id": "doi:a", "title": "Dividends of Expanding Clean-Cooking Fuel Access: Rural-Urban Evidence",
            "abstract": "", "similarity": 0.764}
    cited = {"arxiv_id": "doi:b", "title": "Rural cooking interventions and blood pressure",
             "abstract": "", "similarity": 0.611}
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=_note_db())
    f = _finding("doi:b", "Rural cooking interventions", [best, cited], ["rural"])

    agent._verify_evidence_spans([f])

    assert f.verdict == "UNCERTAIN"
    assert "less similar" in f.checks


def test_top_candidate_with_span_and_key_term_passes():
    top = {"arxiv_id": "doi:a", "title": "Fueling Change: Impact of Mass Media on Clean Cooking Fuel Adoption in Rural India",
           "abstract": "", "similarity": 0.750}
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=_note_db())
    f = _finding("doi:a", "Clean Cooking Fuel Adoption in Rural India", [top], ["rural"])

    agent._verify_evidence_spans([f])

    assert f.verdict == "LIKELY_ADDRESSED"
    assert f.evidence.startswith("[doi:a] Fueling Change")


# --- excluded scope and relevance filtering ------------------------------------------------

class _KeywordEmbed:
    """Deterministic stand-in: one dimension per keyword."""
    is_loaded = True
    KEYS = ["stove", "combustion", "intervention", "rural", "adoption"]

    def embed(self, text):
        t = text.lower()
        v = [1.0 if k in t else 0.0 for k in self.KEYS] + [0.3]
        return v


def test_candidate_closer_to_an_excluded_topic_than_to_the_claim_is_dropped():
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=_note_db())
    agent._embedder = _KeywordEmbed()
    claim = {"claim": "Rural adoption interventions are rarely evaluated.", "key_terms": ["rural"]}
    injera = {"arxiv_id": "epmc:1", "title": "Enhanced biogas injera baking stove with an inverted conical combustion chamber", "abstract": ""}
    trial = {"arxiv_id": "epmc:2", "title": "Rural adoption intervention trial", "abstract": ""}

    kept = agent._filter_candidates(claim, [injera, trial], excluded=["stove technology design"])

    assert [p["arxiv_id"] for p in kept] == ["epmc:2"]


def test_excluded_topic_phrases_must_be_verbatim_from_constraints():
    constraints = "Reject any research question that widens back out to stove technology design."
    api = MagicMock()
    api.generate_structured.return_value = json.dumps(["stove technology design", "sensor hardware"])
    agent = GapAnalysisAgent(api_model=api, note_db=_note_db(constraints=constraints))
    agent._ensure_deg("sess-1")

    assert agent._excluded_topics("sess-1") == ["stove technology design"]


def test_filtering_is_skipped_without_an_embedding_model():
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=_note_db())
    cands = [{"arxiv_id": "x", "title": "anything", "abstract": ""}]
    assert agent._filter_candidates({"claim": "c", "key_terms": []}, cands, ["stove"]) == cands


# --- report checks ------------------------------------------------------------------

def test_absence_claims_and_uncited_bullets_are_flagged_in_the_report():
    note_db = _note_db()
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=note_db)
    agent._ensure_deg("sess-1")
    report = (
        "1. OPEN PROBLEMS\n"
        "- Fuel stacking persists after LPG adoption [1][5].\n"
        "- No study has examined urban households.\n"
        "- Rural uptake varies by subsidy design [42].\n"
        "2. DISAGREEMENTS\nNOT_APPLICABLE\n"
    )

    checked = agent._append_report_checks(report, n_papers=20)

    assert "## Automated report checks" in checked
    assert "No study has examined urban households." in checked.split("## Automated report checks")[1]
    assert "[42]" in checked.split("outside [1]-[20]")[1]
    assert any(c.args[1:3] == (3, "gap_report_checks") for c in note_db.save_degradation.call_args_list)


def test_clean_report_is_returned_unchanged():
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=_note_db())
    report = "- Fuel stacking persists after LPG adoption [1][5].\n2. DISAGREEMENTS\nNOT_APPLICABLE"
    assert agent._append_report_checks(report, n_papers=20) == report


def test_gap_prompt_has_no_ml_specific_sections_and_allows_not_applicable():
    from agents.gap_analysis import _GAP_PROMPT
    assert "ablation" not in _GAP_PROMPT.lower()
    assert "NOT_APPLICABLE" in _GAP_PROMPT
    assert "cite" in _GAP_PROMPT.lower()
