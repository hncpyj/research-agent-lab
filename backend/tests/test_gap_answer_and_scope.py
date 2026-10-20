"""
Gap validation must check that a paper answered a gap, not that it shares its
words, and the gap report must respect the brief's deliberate scope.

Background (2026-09-13, run e6cb1ae3): every gap was CONTRADICTED_BY_COLLECTION
because "7 collected paper(s) contain every key term (fuel costs, clean cooking
fuel)" — any paper discussing fuel costs contains both. One claim had a single
key term ("financial costs"). The report checks flagged bullets under
NOT_APPLICABLE as uncited, and "SETTINGS NOT COVERED" listed high-income
countries for a brief scoped to low- and middle-income countries. The texts
below are from runs e6cb1ae3 and c5a020c3.
"""
import json
from unittest.mock import MagicMock, patch

from agents.gap_analysis import GapAnalysisAgent, _answer_quote_problem, _scope_quote_problem

SOURCE_2021 = {"arxiv_id": "epmc:ELAG", "year": 2021,
               "title": "Enhancing LPG Adoption in Ghana (ELAG): A Trial Testing Policy-Relevant Interventions",
               "abstract": "", "findings": "",
               "future_work": "Further research is needed on fuel subsidies and sustained use of clean fuels."}
POLICY_2025 = {"arxiv_id": "epmc:GD", "year": 2025,
               "title": "Global Disparities in Clean Cooking Fuel Adoption: Barriers, Opportunities, and Policy Pathways",
               "abstract": "We propose policy pathways in which fuel subsidies and microloans support sustained use "
                           "of clean fuels. Governments should expand fuel subsidies to sustain clean fuels use.",
               "findings": ""}
TRIAL_2024 = {"arxiv_id": "epmc:TR", "year": 2024, "title": "LPG subsidy trial",
              "abstract": "In a randomised trial, fuel subsidies raised sustained use of clean fuels by 18 "
                          "percentage points after twelve months.",
              "findings": ""}

CLAIM = {"claim": "Effectiveness of fuel subsidies in increasing sustained use of clean fuels is unaddressed",
         "search_query": "fuel subsidies sustained use clean fuels",
         "key_terms": ["fuel subsidies", "clean fuels"], "source_papers": [1]}


def _note_db(papers, constraints=""):
    db = MagicMock()
    db.get_papers.return_value = list(papers)
    db.get_session.return_value = {"constraints": constraints, "goals": "", "background": ""}
    db.get_degradations.return_value = []
    return db


def _validate(papers, claim, answer_reply):
    api = MagicMock()
    api.generate_structured.side_effect = [json.dumps([claim]), "[]"]
    api.generate.return_value = answer_reply
    agent = GapAnalysisAgent(api_model=api, note_db=_note_db(papers))
    with patch("tools.sources.search_all", return_value=([], {})) as search:
        _, findings = agent.validate_gap_report("topic", "- Subsidy effects need study [1].", "sess-1")
    return findings[0], api, search


# --- answering, not co-occurrence -------------------------------------------------------

def test_a_later_paper_sharing_the_terms_but_only_recommending_does_not_close_the_gap():
    reply = "ANSWERS: yes\nQUOTE: Governments should expand fuel subsidies to sustain clean fuels use."
    finding, _, search = _validate([SOURCE_2021, POLICY_2025], CLAIM, reply)
    assert finding.verdict != "CONTRADICTED_BY_COLLECTION"
    assert "none was shown to report a result" in finding.checks
    search.assert_called()                                    # external validation now runs


def test_a_quote_not_in_the_paper_does_not_close_the_gap():
    reply = "ANSWERS: yes\nQUOTE: Fuel subsidies doubled sustained use of clean fuels across Ghana."
    finding, _, _ = _validate([SOURCE_2021, TRIAL_2024], CLAIM, reply)
    assert finding.verdict != "CONTRADICTED_BY_COLLECTION"


def test_a_later_paper_quoting_a_reported_result_closes_the_gap():
    reply = ("ANSWERS: yes\nQUOTE: In a randomised trial, fuel subsidies raised sustained use of clean "
             "fuels by 18 percentage points after twelve months.")
    finding, _, search = _validate([SOURCE_2021, TRIAL_2024], CLAIM, reply)
    assert finding.verdict == "CONTRADICTED_BY_COLLECTION"
    assert "18 percentage points" in finding.evidence
    search.assert_not_called()


def test_model_saying_no_does_not_close_the_gap():
    finding, _, _ = _validate([SOURCE_2021, TRIAL_2024], CLAIM, "ANSWERS: no\nQUOTE: none")
    assert finding.verdict != "CONTRADICTED_BY_COLLECTION"


def test_a_claim_with_one_key_term_skips_the_collection_check():
    claim = dict(CLAIM, key_terms=["fuel subsidies"])
    finding, api, search = _validate([SOURCE_2021, TRIAL_2024], claim, "ANSWERS: yes\nQUOTE: x")
    assert finding.verdict != "CONTRADICTED_BY_COLLECTION"
    assert "fewer than 2 key terms" in finding.checks
    api.generate.assert_not_called()
    search.assert_called()


def test_answer_quote_checks():
    terms = ["fuel subsidies", "clean fuels"]
    assert _answer_quote_problem("none", TRIAL_2024, terms) == "no result sentence quoted"
    assert "recommends" in _answer_quote_problem(
        "Governments should expand fuel subsidies to sustain clean fuels use.", POLICY_2025, terms)
    assert _answer_quote_problem(
        "In a randomised trial, fuel subsidies raised sustained use of clean fuels by 18 percentage points",
        TRIAL_2024, terms) is None


# --- report checks ------------------------------------------------------------------------

REPORT_C5A020C3 = """**SETTINGS, POPULATIONS OR DATA THIS COLLECTION DOES NOT COVER**

* The collection does not cover the use of clean cooking fuels in high-income countries, as mentioned in [3].
* The collection does not include data on individual-level risk factors that can be matched with available mortality data, as mentioned in [19].

**NOT_APPLICABLE**

* There are no disagreements or conflicting findings between papers on the topic of fuel stacking and clean cooking transitions.
* There are no open problems or gaps in the literature that are not addressed by the authors themselves."""

BRIEF = ("Topic: Sustained adoption and fuel stacking after clean cooking transitions in low- and "
         "middle-income countries\nConstraints: Open data only.")


def test_bullets_under_not_applicable_are_not_flagged_as_uncited():
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=_note_db([]))
    report = REPORT_C5A020C3 + "\n\n**DISAGREEMENTS**\n\n- Stacking is common everywhere.\n"
    checked = agent._append_report_checks(report, n_papers=20)
    flagged = checked.split("## Automated report checks")[1]
    assert "There are no disagreements" not in flagged
    assert "Stacking is common everywhere." in flagged            # a real section is still checked


def test_uncovered_setting_the_brief_excludes_is_removed_and_listed():
    api = MagicMock()
    api.generate.side_effect = [
        "OUTSIDE_SCOPE: yes\nBRIEF_QUOTE: low- and middle-income countries",
        "OUTSIDE_SCOPE: no\nBRIEF_QUOTE: none",
    ]
    agent = GapAnalysisAgent(api_model=api, note_db=_note_db([]))

    report, removed = agent._remove_out_of_scope_settings(REPORT_C5A020C3, BRIEF)
    checked = agent._append_report_checks(report, 20, removed)

    body, checks = checked.split("## Automated report checks")
    assert "high-income countries" not in body
    assert "individual-level risk factors" in body
    assert "high-income countries" in checks and "low- and middle-income countries" in checks
    assert api.generate.call_count == 2                           # only the SETTINGS bullets were checked


def test_out_of_scope_claim_needs_a_real_brief_quote():
    api = MagicMock()
    api.generate.side_effect = [
        "OUTSIDE_SCOPE: yes\nBRIEF_QUOTE: only upper-middle-income settings",   # not in the brief
        "OUTSIDE_SCOPE: yes\nBRIEF_QUOTE: Open data only",                        # shares no word
    ]
    agent = GapAnalysisAgent(api_model=api, note_db=_note_db([]))
    report, removed = agent._remove_out_of_scope_settings(REPORT_C5A020C3, BRIEF)
    assert removed == []
    assert report == REPORT_C5A020C3
    assert _scope_quote_problem("Open data only", BRIEF, "individual-level risk factors data") \
        == "quote shares no word with the listed setting"


def test_gap_prompt_passes_the_brief_scope():
    api = MagicMock()
    api.generate.return_value = "a gap report"
    agent = GapAnalysisAgent(api_model=api, note_db=_note_db([], constraints="Open data only."))
    agent._analyse_gaps("Clean cooking in low- and middle-income countries", "summary", 20, "sess-1")
    prompt = api.generate.call_args_list[0].kwargs["prompt"]
    assert "Constraints: Open data only." in prompt
    assert "deliberately leaves out" in prompt


ECUADOR_2023 = {  # [19] in run c5a020c3, findings as extracted from the full text
    "title": "Widespread Clean Cooking Fuel Scale-Up and under-5 Lower Respiratory Infection Mortality: "
             "An Ecological Analysis in Ecuador, 1990-2019",
    "abstract": "", "findings": "Canton-level clean fuel use was negatively associated with under-5 LRI "
                                "mortalities in linear and nonlinear models."}


def test_real_result_sentence_passes_without_repeating_every_key_term_word():
    # Measured with llama3.1:8b on 2026-09-13: the all-words rule rejected this true answer.
    quote = "Canton-level clean fuel use was negatively associated with under-5 LRI mortalities in linear and nonlinear models."
    assert _answer_quote_problem(quote, ECUADOR_2023, ["clean cooking fuel", "mortality"]) is None


def test_irrelevant_quote_the_8b_model_gave_for_a_subsidy_gap_is_rejected():
    # Same run: the model answered "yes" for [3] and quoted an access-disparity sentence.
    paper = {"title": "Global Disparities", "findings": "",
             "abstract": "High-income countries have achieved nearly universal access, while South Asia lags behind."}
    quote = "High-income countries have achieved nearly universal access, while South Asia lags behind."
    assert _answer_quote_problem(quote, paper, ["fuel subsidies", "clean fuels"]) \
        == "quote contains fewer than half of the key-term words"


def test_scope_removal_alone_does_not_record_a_report_problem():
    note_db = _note_db([])
    agent = GapAnalysisAgent(api_model=MagicMock(), note_db=note_db)
    agent._ensure_deg("sess-1")
    agent._append_report_checks("- Stacking persists [1].", 20, [("high-income countries [3]", "low- and middle-income countries")])
    assert not any(c.args[2] == "gap_report_checks" for c in note_db.save_degradation.call_args_list)
