"""
Which papers may count as evidence that a gap is already closed.

Background (2026-09-13 run e6cb1ae3): gaps now come from the collected
papers' own future-work and limitation statements. The collection-first
check, built for free-generated gaps, then marked all six as
CONTRADICTED_BY_COLLECTION — each "contradicted" by the very paper that
raised it. A gap taken from a paper's future work needs a recency check, not
a novelty check: did anyone do it after that paper? So only papers published
later than the source can contradict it, and only through what they report
(title, abstract, findings) — a second paper also saying "more research is
needed" is a second piece of evidence the gap exists, not that it closed.
"""
import json
from unittest.mock import MagicMock, patch

from agents.gap_analysis import GapAnalysisAgent, _contradicting_papers


def _paper(n, year, title="", abstract="", findings="", limitation="", future_work=""):
    return {"arxiv_id": f"p{n}", "year": year, "title": title, "abstract": abstract,
            "findings": findings, "limitation": limitation, "future_work": future_work}


SUBSIDY = ["fuel subsidies", "sustained use"]


def test_the_source_paper_cannot_contradict_its_own_gap():
    source = _paper(1, 2020, title="Fuel subsidies and sustained use of LPG in Ghana")
    claim = {"key_terms": SUBSIDY, "source_papers": [1]}
    assert _contradicting_papers(claim, [source]) == []


def test_older_or_same_year_papers_cannot_contradict_a_future_work_gap():
    source = _paper(1, 2020, future_work="Future research should test fuel subsidies on sustained use.")
    older = _paper(2, 2018, title="Fuel subsidies and sustained use in India")
    same_year = _paper(3, 2020, title="Fuel subsidies and sustained use in Kenya")
    claim = {"key_terms": SUBSIDY, "source_papers": [1]}
    assert _contradicting_papers(claim, [source, older, same_year]) == []


def test_a_later_paper_reporting_it_does_contradict():
    source = _paper(1, 2020, future_work="Future research should test fuel subsidies on sustained use.")
    later = _paper(2, 2023, title="Effect of fuel subsidies on sustained use: a trial")
    claim = {"key_terms": SUBSIDY, "source_papers": [1]}
    assert _contradicting_papers(claim, [source, later]) == [later]


def test_a_later_paper_that_only_repeats_the_call_for_research_does_not_contradict():
    source = _paper(1, 2020, future_work="Future research should test fuel subsidies on sustained use.")
    also_calls = _paper(2, 2024, title="Household energy in Ghana",
                        future_work="The effect of fuel subsidies on sustained use remains unknown.",
                        limitation="We could not assess fuel subsidies or sustained use.")
    claim = {"key_terms": SUBSIDY, "source_papers": [1]}
    assert _contradicting_papers(claim, [source, also_calls]) == []


def test_with_several_sources_the_latest_source_sets_the_cutoff():
    s1 = _paper(1, 2018, title="x")
    s2 = _paper(2, 2022, title="y")
    between = _paper(3, 2020, title="Fuel subsidies and sustained use")
    after = _paper(4, 2024, title="Fuel subsidies and sustained use")
    claim = {"key_terms": SUBSIDY, "source_papers": [1, 2]}
    assert _contradicting_papers(claim, [s1, s2, between, after]) == [after]


def test_free_generated_claim_without_sources_uses_any_reporting_paper():
    paper = _paper(1, 2015, title="Fuel subsidies and sustained use of LPG")
    claim = {"key_terms": SUBSIDY, "source_papers": []}
    assert _contradicting_papers(claim, [paper]) == [paper]


def test_source_numbers_not_cited_in_the_report_are_dropped():
    extract = json.dumps([{
        "claim": "The effect of fuel subsidies on sustained use is untested.",
        "search_query": "fuel subsidies sustained use clean cooking",
        "key_terms": ["fuel subsidies", "sustained use"],
        "source_papers": [11, 99],
    }])
    api = MagicMock()
    api.generate_structured.return_value = extract
    agent = GapAnalysisAgent(api_model=api, note_db=MagicMock())

    claims = agent._extract_claims("topic", "- Subsidy effects on sustained use need study [11].")

    assert claims[0]["source_papers"] == [11]


def test_external_candidates_older_than_the_source_are_not_used_as_evidence():
    note_db = MagicMock()
    note_db.get_papers.return_value = [_paper(1, 2020, title="Ghana LPG trial")] + [
        _paper(n, 2019, title=f"p{n}") for n in range(2, 12)
    ]
    note_db.get_session.return_value = {"constraints": ""}
    note_db.get_degradations.return_value = []
    extract = json.dumps([{
        "claim": "The effect of fuel subsidies on sustained use is untested.",
        "search_query": "fuel subsidies sustained use",
        "key_terms": ["fuel subsidies"],
        "source_papers": [1],
    }])
    api = MagicMock()
    api.generate_structured.side_effect = [extract, "[]"]
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)
    old = MagicMock(arxiv_id="doi:old", title="Fuel subsidies in 2015", year=2015, abstract="")
    new = MagicMock(arxiv_id="doi:new", title="Fuel subsidies in 2023", year=2023, abstract="")

    with patch("tools.sources.search_all", return_value=([old, new], {})):
        _, findings = agent.validate_gap_report("topic", "- Subsidy effects need study [1].", "sess-1")

    ids = [p["arxiv_id"] for p in findings[0].papers_found]
    assert ids == ["doi:new"]
