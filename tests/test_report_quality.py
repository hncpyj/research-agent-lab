"""
M8 — problems found by reading the first finished report (session 8e3e3603,
2026-09-20) end to end.

- its reference list was renumbered, so every citation named a different paper
- the abstract opened "This study examines the country-level conditions…" when
  the conditions were the one thing the data could not test
- related work carried a NOT_APPLICABLE block saying there were no
  disagreements, printed directly under two of them
- the introduction printed instructions written for the agent
- claim IDs (C1, H1.T1) appeared in the prose
- no claim said how many countries it rested on
- the plan classified a percentage indicator with no saturation cut-off and a
  threshold of 0.05 points per year
"""
from agents.analysis_plan import auto_threats
from agents.claims_report import (
    ClaimsReportWriter,
    brief_background,
    clean_gap_report,
    coverage_sentence,
    provenance_line,
)
from agents.plan_review import review
from tests.test_results_and_claims import AUDIT, HYPOTHESES, PLAN, _results
from ui.report_renderer import to_html, to_latex, to_markdown

REPORT = {
    "title": "T", "abstract": "a", "results": "see [11]", "limitations": "l", "review": "- [warn] check this",
    "references": [{"key": "[11]", "title": "ELAG Ghana", "authors": "A", "venue": "europepmc", "year": "2021"},
                   {"key": "[19]", "title": "Ecuador", "authors": "B", "venue": "europepmc", "year": "2023"}],
}


def test_renderers_keep_the_citation_numbers_the_text_uses():
    md, tex, html = to_markdown(REPORT), to_latex(REPORT), to_html(REPORT)
    assert "[11] A. *ELAG Ghana*" in md and "[19] B." in md
    assert "[1] A." not in md and "[2] B." not in md
    assert "[11]" in tex and "[19]" in tex
    assert "[11]" in html and "<ol>" not in html
    assert "Review notes" in md and "check this" in md


def test_gap_report_becomes_related_work_without_its_contradictory_block():
    text = ("**COLLECTION HEALTH:** Semantic Scholar unreachable.\n\n"
            "**DISAGREEMENTS OR CONFLICTING FINDINGS**\n\n"
            "* [19] found lower mortality, [12] found no improvement.\n\n"
            "**NOT_APPLICABLE**\n\n"
            "* There are no disagreements or conflicting findings between papers.\n")
    cleaned = clean_gap_report(text)
    assert "found lower mortality" in cleaned
    assert "NOT_APPLICABLE" not in cleaned and "There are no disagreements" not in cleaned
    assert "COLLECTION HEALTH" not in cleaned            # it is already in the limitations


def test_background_keeps_the_science_and_drops_instructions_to_the_agent():
    brief = ("Household air pollution is associated with a large annual burden of premature death. "
             "Treat both of those as claims to verify against sources during the literature phase. "
             "WHO publishes a household air pollution bulk download. "
             "One warning about your own paper collection: an arXiv-only search will return nothing.")
    kept = brief_background(brief)
    assert "large annual burden" in kept and "WHO publishes" in kept
    assert "Treat both" not in kept and "your own paper collection" not in kept


def test_unanswered_parts_must_be_stated_and_internal_ids_do_not_reach_the_prose(tmp_path):
    table = _results(tmp_path)
    assert "no variable" in coverage_sentence(table)
    from unittest.mock import MagicMock
    api = MagicMock()
    api.generate.side_effect = [
        "CLAIM: C1\nTEXT: Among 81 countries urban use rose 0.30 points per year faster.\nEVIDENCE: R2\n",
        "Urban use rose faster (C1).",                                   # abstract: hides what was untested
        "Urban use rose faster (C1); the data has no variable for policies, prices or income.",
        "Discussion (C1).",
        "Conclusion: policies, prices and income could not be measured (C1).",
    ]
    writer = ClaimsReportWriter(api, MagicMock())
    claims = writer.claims("Q?", table, PLAN)
    report = writer.report({"research_question": "Q?", "gap_report": ""}, AUDIT, HYPOTHESES, PLAN, table, claims,
                           [], {"session_id": "s1", "code_hash": "abc123def456789", "run_at": "2026-09-20T01:00:00",
                                "plan_version": 2})
    assert "no variable for policies" in report["abstract"]
    assert "(C1)" not in report["abstract"] and "(C1)" not in report["conclusion"]
    assert report["methodology"].startswith("Provenance: Session s1; analysis code abc123def456")


def test_a_claim_without_its_sample_size_is_flagged(tmp_path):
    from agents.claims_report import claim_problems
    table = _results(tmp_path)
    rows = {r["id"]: r for r in table["rows"]}
    plan_tests = {t["id"]: t for t in PLAN["tests"]}
    problems = claim_problems({"text": "Urban use rose 0.30 points per year faster.", "evidence": ["R2"]},
                              rows, plan_tests, table, PLAN)
    assert any("how many countries" in p for p in problems)


def test_plan_adds_the_threats_a_reader_must_know(tmp_path):
    indicators = {"CLEAN": {"code": "CLEAN", "unit": "%"}, "DEATHS": {"code": "DEATHS", "unit": "per 100 000"}}
    same = auto_threats("trajectory_group_comparison",
                        {"indicator": "CLEAN", "indicator_y": "CLEAN", "threshold": 0.25}, indicators)
    assert any("not independent" in n for n in same)
    assert any("saturation" in n for n in same)          # percentage indicator, no cut-off given
    with_cut = auto_threats("trajectory_class", {"indicator": "CLEAN", "saturation": 95.0}, indicators)
    assert with_cut == []
    other_unit = auto_threats("trajectory_class", {"indicator": "DEATHS"}, indicators)
    assert other_unit == []


def test_a_threshold_below_the_data_movement_is_reported():
    import pandas as pd
    from tools.analysis_blocks import _threshold_note
    series = pd.DataFrame({"recent_slope": [0.4, 0.8, 1.2, -0.6]})
    assert _threshold_note(series, 0.05)
    assert _threshold_note(series, 0.25) == []


def test_review_flags_citations_that_are_not_in_the_reference_list(tmp_path):
    table = _results(tmp_path)
    claims = {"accepted": [], "rejected": []}
    report = dict(REPORT, results="see [11] and [42]", limitations="Stricter energy policies raise clean fuel use. "
                                                                  "The impact of policies, prices, or income on clean "
                                                                  "fuel adoption. judge failed")
    findings = review(HYPOTHESES, PLAN, table, claims, report)
    citation_fails = [f for f in findings if f["check"] == "citations"]
    assert citation_fails and "[42]" in citation_fails[0]["detail"] and "[11]" not in citation_fails[0]["detail"]


def test_provenance_is_empty_when_unknown():
    assert provenance_line(None) == ""


def test_missing_sample_size_is_added_not_rejected(tmp_path):
    from agents.claims_report import with_counts
    table = _results(tmp_path)
    rows = {r["id"]: r for r in table["rows"]}
    text = with_counts("Urban use rose 0.30 points per year faster.", [rows["R2"]])
    assert text.endswith("(n = 81 countries).")
    assert with_counts("Across 81 countries urban use rose faster.", [rows["R2"]]) == \
        "Across 81 countries urban use rose faster."
    assert with_counts("The policy question is untestable.", [rows["R4"]]) == "The policy question is untestable."


# --- M9: the first full c5a020c3 run (2026-09-20) --------------------------------

def test_a_significance_word_must_match_the_interval(tmp_path):
    from agents.claims_report import significance_problem
    excludes_zero = {"id": "R1", "block": "paired_difference",
                     "values": {"mean": -0.1522, "ci_low": -0.2893, "ci_high": -0.0264}}
    spans_zero = {"id": "R2", "block": "paired_difference",
                  "values": {"mean": -0.15, "ci_low": -0.52, "ci_high": 0.22}}
    share = {"id": "R3", "block": "class_agreement",
             "values": {"disagreement_share": 0.36, "ci_low": 0.29, "ci_high": 0.43}}
    # the two contradicting claims the report actually printed
    assert significance_problem("The trend is significantly lower in urban areas.", excludes_zero) is None
    assert "excludes zero" in significance_problem("The relationship is not statistically significant.", excludes_zero)
    assert "includes zero" in significance_problem("The difference is significant.", spans_zero)
    assert significance_problem("The relationship is not significant.", spans_zero) is None
    assert significance_problem("Urban and rural series diverge significantly.", share) is None


def test_every_decided_result_reaches_the_claims(tmp_path):
    from unittest.mock import MagicMock
    table = _results(tmp_path)          # R1 rejected, R2 supported, R3/R4 untestable
    api = MagicMock()
    covers_one = "CLAIM: C1\nTEXT: In 81 countries the gap is 0.30 per year.\nEVIDENCE: R2\n"
    api.generate.side_effect = [covers_one, covers_one]
    deg = MagicMock()
    claims = ClaimsReportWriter(api, deg).claims("Q?", table, PLAN)

    assert api.generate.call_count == 2                       # asked again for the missing row
    covered = {e for c in claims["accepted"] for e in c["evidence"]}
    assert {"R1", "R2"} <= covered
    written = [c for c in claims["accepted"] if c.get("generated")]
    assert len(written) == 1 and "rejected" in written[0]["text"]
    assert deg.record.call_args.args[:3] == (7, "claims", "warn")


def test_a_claim_must_face_the_same_way_as_the_estimate(tmp_path):
    from agents.claims_report import direction_problem
    meanings = {"RESIDENCEAREATYPE_URB": "Urban", "RESIDENCEAREATYPE_RUR": "Rural"}
    test = {"typed_params": {"pair": "Dim1:RESIDENCEAREATYPE_URB,RESIDENCEAREATYPE_RUR"}}
    urban_faster = {"id": "R2", "test": "T", "block": "paired_difference", "values": {"mean": 0.3008}}
    urban_slower = {"id": "R1", "test": "T", "block": "paired_difference", "values": {"mean": -0.1522}}
    wrong = "The trend is significantly lower in urban areas than in rural areas in these countries."
    assert "R2 is +0.3008" in direction_problem(wrong, urban_faster, test, meanings)
    assert direction_problem(wrong, urban_slower, test, meanings) is None
    right = "Clean fuel use rose faster in urban areas than in rural areas."
    assert direction_problem(right, urban_faster, test, meanings) is None
    assert "R1 is -0.1522" in direction_problem(right, urban_slower, test, meanings)
