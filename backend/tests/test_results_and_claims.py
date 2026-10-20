"""
Stages S7-S9: results table, claim checks, review.

The rejected sentences are the ones the 2026-09-13 report for session c5a020c3
actually printed, checked against the results that session actually produced.
"""
import json
from unittest.mock import MagicMock

from agents import results_table
from agents.claims_report import ClaimsReportWriter, claim_problems, limitations, parse_claims, wording_problems
from agents.plan_review import model_issues, review

PLAN = {"tests": [
    {"id": "H2.T1", "hypothesis": "H2", "compares": "urban minus rural yearly trend within countries",
     "block": "paired_difference", "support_if": "mean > 0 AND ci_low > 0", "reject_if": "ci_high < 0",
     "threats": "modelled values", "typed_params": {"indicator": "CLEAN", "stat": "slope", "window": 5}},
    {"id": "H2.T2", "hypothesis": "H2", "compares": "same, countries below 95% in both areas",
     "block": "paired_difference", "support_if": "mean > 0 AND ci_low > 0", "reject_if": "ci_high < 0",
     "threats": "", "typed_params": {"indicator": "CLEAN", "stat": "slope", "exclude_at_or_above": 95.0}},
]}
HYPOTHESES = {"selected": ["H2"], "hypotheses": [
    {"id": "H1", "statement": "Stricter energy policies raise clean fuel use.", "testable": False,
     "problems": ["energy policy stringency: not in the data"], "rows": []},
    {"id": "H2", "statement": "Urban clean fuel use rises faster than rural.", "testable": True,
     "cannot_test": "The impact of policies, prices, or income on clean fuel adoption.", "rows": []},
]}
AUDIT = {"source": "who", "indicators": [], "limits": ["Values are not labelled as measured or modelled."]}


def _results(tmp_path):
    folder = tmp_path
    (folder / "results").mkdir(exist_ok=True)
    (folder / "results" / "H2.T1.json").write_text(json.dumps({"outputs": {
        "mean": -0.1522, "ci_low": -0.2893, "ci_high": -0.0264, "n_units": 194}}))
    (folder / "results" / "H2.T2.json").write_text(json.dumps({"outputs": {
        "mean": 0.3008, "ci_low": 0.1285, "ci_high": 0.4782, "n_units": 81}, "notes": ["113 units excluded"]}))
    return results_table.build(PLAN, HYPOTHESES, folder, [
        {"severity": "critical", "phase": 7, "component": "ai_judge", "message": "judge failed"}])


def test_verdicts_follow_the_pre_registered_rules(tmp_path):
    table = _results(tmp_path)
    rows = {r["test"] or r["hypothesis"]: r for r in table["rows"]}
    assert rows["H2.T1"]["verdict"] == "rejected"
    assert rows["H2.T2"]["verdict"] == "supported"
    assert rows["H2.T2"]["source"] == "results/H2.T2.json"
    untestable = [r for r in table["rows"] if r["verdict"] == "untestable"]
    assert {r["hypothesis"] for r in untestable} == {"H1", "H2"}         # H1 itself, and H2's CANNOT_TEST part
    assert table["hypothesis_summary"] == {"H2": "mixed"}


def test_missing_or_failed_results_are_undetermined(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "H2.T1.json").write_text(json.dumps({"error": "PanelDataError: no rows"}))
    table = results_table.build(PLAN, {"selected": [], "hypotheses": []}, tmp_path, [])
    assert [r["verdict"] for r in table["rows"]] == ["undetermined", "undetermined"]


def _check(text, evidence, tmp_path):
    table = _results(tmp_path)
    rows = {r["id"]: r for r in table["rows"]}
    return claim_problems({"text": text, "evidence": evidence}, rows, {t["id"]: t for t in PLAN["tests"]}, table, PLAN)


def test_sentences_from_the_old_report_are_rejected(tmp_path):
    policy = _check("Countries with rising clean fuel reliance have more stringent energy policies.", ["R3"], tmp_path)
    assert policy
    faster = _check("Urban areas experienced a faster rise in clean fuel reliance, as shown by a mean difference of 0.30.",
                    ["R1"], tmp_path)
    assert any("not in the cited results" in p for p in faster)          # 0.30 belongs to R2, not R1
    table = _results(tmp_path)
    robust = wording_problems("Our results are consistent across different sensitivity analyses and robust.", table, PLAN)
    assert any("sensitivity" in p for p in robust)
    policies = wording_problems("Countries with weaker policies stalled.", table, PLAN)
    assert any("policies" in p for p in policies)


def test_a_correct_claim_passes(tmp_path):
    text = ("Among 81 countries below 95% in both areas, urban clean fuel use rose 0.30 percentage points per "
            "year faster than rural (95% CI 0.13 to 0.48).")
    assert _check(text, ["R2"], tmp_path) == []


def test_rejected_result_cannot_be_called_support_and_causal_words_are_refused(tmp_path):
    assert any("not 'supported'" in p for p in
               _check("Across 194 countries the difference of -0.15 supports H2.", ["R1"], tmp_path))
    assert _check("Across 194 countries the difference of -0.15 does not support H2.", ["R1"], tmp_path) == []
    assert any("causal" in p for p in _check("Urbanisation drives a 0.30 gap in 81 countries.", ["R2"], tmp_path))
    assert any("how many countries" in p for p in
               _check("The difference of -0.15 does not support H2.", ["R1"], tmp_path))


def test_limitations_include_untestable_items_and_critical_problems(tmp_path):
    table = _results(tmp_path)
    items = limitations(table, PLAN, AUDIT)
    text = " ".join(items)
    assert "Stricter energy policies" in text and "judge failed" in text and "113 units excluded" in text


def test_report_sections_fall_back_to_claims_when_the_model_invents(tmp_path):
    table = _results(tmp_path)
    api = MagicMock()
    api.generate.side_effect = [
        # the model never mentions R1, so it is asked again and a claim is written from the row
        "CLAIM: C1\nTEXT: Among 81 countries below 95% in both areas, urban use rose 0.30 points faster per year.\nEVIDENCE: R2\n",
        "CLAIM: C1\nTEXT: Among 81 countries below 95% in both areas, urban use rose 0.30 points faster per year.\nEVIDENCE: R2\n",
        "This proves stricter policies raise adoption by 45%.", "Still 45% and robust.",   # abstract x2
        "Discussion text without numbers.",                                                # discussion
        "Conclusion: policies, prices and income could not be measured.",                  # conclusion
    ]
    deg = MagicMock()
    writer = ClaimsReportWriter(api, deg)
    claims = writer.claims("Q?", table, PLAN)
    # C1 from the model, plus a claim written from R1 (rejected) which it never mentioned
    assert [c["id"] for c in claims["accepted"]] == ["C1", "C2"]
    assert claims["accepted"][1]["evidence"] == ["R1"] and claims["accepted"][1]["generated"]
    report = writer.report({"research_question": "Q?", "gap_report": "- gap [1]"}, AUDIT, HYPOTHESES, PLAN, table,
                           claims, [{"title": "Paper one"}])
    assert report["abstract"].startswith("- Among 81 countries")
    assert "Stricter energy policies" in report["limitations"]
    assert report["references"][0]["title"] == "Paper one"
    assert deg.record.call_args.args[:2] == (7, "report")

    findings = review(HYPOTHESES, PLAN, table, claims, report)
    assert not [f for f in findings if f["level"] == "fail"], findings


def test_model_review_issues_must_cite_existing_ids():
    api = MagicMock()
    api.generate.return_value = "ISSUE: R2 | excludes saturated countries\nISSUE: R9 | invented\nISSUE: none"
    issues = model_issues(api, "Q", "table", {"accepted": []}, {"R1", "R2"})
    assert [i["detail"] for i in issues] == ["R2: excludes saturated countries"]


def test_claim_parser():
    raw = "**CLAIM: C1**\nTEXT: A 0.30 gap.\nEVIDENCE: R2, R1\nCLAIM: C2\nEVIDENCE: R1"
    assert parse_claims(raw) == [{"id": "C1", "text": "A 0.30 gap.", "evidence": ["R2", "R1"]}]


def test_at_least_the_point_estimate_is_an_overstatement():
    # 2026-09-14 replay of c5a020c3: estimate 29.63, CI 14.07-45.17
    table = {"rows": [{"id": "R1", "values": {"difference": 29.63, "ci_low": 14.07, "ci_high": 45.17}},
                      {"id": "R3", "values": {"disagreement_share": 0.3041, "ci_low": 0.2437, "ci_high": 0.3721}}]}
    from agents.claims_report import bound_problems
    assert bound_problems("The difference is at least 29.63 percentage points.", table)
    assert bound_problems("The difference is at least 14.07 percentage points.", table) == []
    assert bound_problems("Disagreement is below 30.41% of countries.", table)
    assert bound_problems("The estimate was 29.63 (CI 14.07 to 45.17).", table) == []


def test_limitations_skip_data_limits_about_unused_indicators():
    audit = {"indicators": [{"code": "CLEAN"}, {"code": "AIR_11"}],
             "limits": ["AIR_11 covers a single year (2021): no trend analysis possible.",
                        "CLEAN values are modelled.", "How values were produced is not stated."]}
    plan = {"tests": [{"id": "T", "threats": "", "typed_params": {"indicator": "CLEAN"}}]}
    items = limitations({"rows": [], "critical_degradations": []}, plan, audit)
    assert "CLEAN values are modelled." in items and "How values were produced is not stated." in items
    assert not any("AIR_11" in i for i in items)


def test_the_observational_disclaimer_is_not_causal_wording(tmp_path):
    table = _results(tmp_path)
    assert wording_problems("These associations do not establish a causal relationship.", table, PLAN) == []
    assert wording_problems("Urbanisation causes faster adoption.", table, PLAN)


def test_accepted_claims_come_from_a_single_attempt(tmp_path):
    table = _results(tmp_path)
    api = MagicMock()
    api.generate.side_effect = [
        "CLAIM: C1\nTEXT: In 81 countries the gap is 0.30 per year.\nEVIDENCE: R2\n"
        "CLAIM: C2\nTEXT: In 81 countries the gap is at least 0.30.\nEVIDENCE: R2\n",
        "CLAIM: C1\nTEXT: In 81 countries the gap is 0.30 per year (95% CI 0.13 to 0.48).\nEVIDENCE: R2\n",
    ]
    claims = ClaimsReportWriter(api).claims("Q?", table, PLAN)
    assert claims["accepted"][0]["text"] == "In 81 countries the gap is 0.30 per year (95% CI 0.13 to 0.48)."
    assert [c.get("generated") for c in claims["accepted"]] == [None, True]      # R1 covered by a written claim
    assert len(claims["rejected"]) == 1
