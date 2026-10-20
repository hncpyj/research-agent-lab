"""
Stage S4: analysis plan parsing and validation.

PLAN_8B holds replies llama3.1:8b actually gave for session c5a020c3 on
2026-09-14: commas between parameters, plain names ("urban,rural") instead of
codes, placeholders copied from the prompt, output names compared with each
other, and a correlation of a statistic with itself.
"""
from agents.analysis_plan import (
    _both_can_hold,
    evaluate_rule,
    parse_plan,
    parse_rule,
    render_plan,
    validate_plan,
)

AREA = [{"code": "RESIDENCEAREATYPE_URB", "meaning": "Urban"}, {"code": "RESIDENCEAREATYPE_RUR", "meaning": "Rural"},
        {"code": "RESIDENCEAREATYPE_TOTL", "meaning": "Total"}]
AUDIT = {
    "indicators": [
        {"code": "CLEAN", "meaning": "Proportion clean fuels (%)", "unit": "%",
         "splits": {"Dim1": AREA}},
        {"code": "DEATHS", "meaning": "attributable death rate", "unit": "per 100 000",
         "splits": {"Dim1": [{"code": "SEX_FMLE", "meaning": "Female"}, {"code": "SEX_MLE", "meaning": "Male"}]}},
    ],
    "groups": {"ParentLocationCode": [{"code": "AFR", "meaning": "Africa"}, {"code": "EUR", "meaning": "Europe"}]},
}
HYPOTHESIS = {"id": "H3", "testable": True, "rows": [
    {"concept": "clean fuel", "variable": "CLEAN", "kind": "indicator", "problem": ""},
    {"concept": "area", "variable": "Dim1:RESIDENCEAREATYPE_URB,RESIDENCEAREATYPE_RUR", "kind": "split", "problem": ""},
    {"concept": "deaths", "variable": "DEATHS", "kind": "indicator", "problem": ""},
]}

PLAN_8B = """TEST: H3.T1
COMPARES: difference in trend between urban and rural areas
BLOCK: paired_difference
PARAMS: indicator=CLEAN, pair=urban,rural, stat=slope, window=10, min_years=5
SUPPORT_IF: mean > 0.5 AND ci_high > 0.2
REJECT_IF: mean <= 0.5
THREATS: short series

TEST: H3.T2
COMPARES: urban versus rural in rising countries
BLOCK: group_comparison
PARAMS: indicator=CLEAN; groups=Column:CODE,REVERSED; stat=slope
SUPPORT_IF: mean_first > mean_second AND ci_low > 0
REJECT_IF: mean_first < mean_second
THREATS: none

TEST: H3.T3
COMPARES: correlation of trends
BLOCK: correlation
PARAMS: indicator_x=CLEAN, indicator_y=CLEAN, stat_x=slope, stat_y=slope
SUPPORT_IF: r > 0.5
REJECT_IF: r <= 0.5
THREATS: other factors
"""


def _validated(text):
    return {t["id"]: t for t in validate_plan(parse_plan(text), {"H3": HYPOTHESIS}, AUDIT)}


def test_commas_and_plain_names_from_the_8b_model_are_read_as_codes():
    t = _validated(PLAN_8B)["H3.T1"]
    assert t["problems"] == []
    assert t["typed_params"]["pair"] == "Dim1:RESIDENCEAREATYPE_URB,RESIDENCEAREATYPE_RUR"
    assert t["typed_params"]["window"] == 10 and t["typed_params"]["bootstrap"] == 2000   # defaults filled


def test_placeholders_and_output_to_output_comparisons_are_rejected():
    problems = " ".join(_validated(PLAN_8B)["H3.T2"]["problems"])
    assert "is not a group of this hypothesis" in problems
    assert "cannot read condition 'mean_first > mean_second'" in problems


def test_correlating_a_statistic_with_itself_is_rejected():
    assert "correlation 1 by construction" in " ".join(_validated(PLAN_8B)["H3.T3"]["problems"])


def test_overlapping_rules_are_found():
    assert _both_can_hold("mean > 0", "mean < 1") is not None
    assert _both_can_hold("mean > 0 AND ci_low > 0", "ci_high < 0") is None     # ci_low <= ci_high
    assert _both_can_hold("r > 0.5", "r <= 0.5") is None


def test_split_must_exist_for_the_indicator_it_is_applied_to():
    text = ("TEST: H3.T1\nCOMPARES: x\nBLOCK: paired_difference\n"
            "PARAMS: indicator=DEATHS; pair=Dim1:RESIDENCEAREATYPE_URB,RESIDENCEAREATYPE_RUR; stat=last_value\n"
            "SUPPORT_IF: mean > 0\nREJECT_IF: mean < 0\nTHREATS: -")
    assert "DEATHS has no split" in " ".join(_validated(text)["H3.T1"]["problems"])


def test_saturation_only_for_percentages_and_circular_class_comparison_rejected():
    text = ("TEST: H3.T1\nCOMPARES: x\nBLOCK: trajectory_group_comparison\n"
            "PARAMS: indicator=CLEAN; classes=rising,not_rising; threshold=0.25; indicator_y=CLEAN; stat_y=slope\n"
            "SUPPORT_IF: difference > 0\nREJECT_IF: difference < 0\nTHREATS: -\n\n"
            "TEST: H3.T2\nCOMPARES: x\nBLOCK: trajectory_class\n"
            "PARAMS: indicator=DEATHS; threshold=0.25; saturation=95\n"
            "SUPPORT_IF: share_rising > 0.5\nREJECT_IF: share_rising < 0.5\nTHREATS: -")
    tests = _validated(text)
    assert "circular" in " ".join(tests["H3.T1"]["problems"])
    assert "only allowed for percentage indicators" in " ".join(tests["H3.T2"]["problems"])


def test_valid_class_comparison_with_within_country_difference():
    text = ("TEST: H3.T1\nCOMPARES: urban minus rural trend in rising vs other countries\n"
            "BLOCK: trajectory_group_comparison\n"
            "PARAMS: indicator=CLEAN; classes=rising,not_rising; threshold=0.25; saturation=95; indicator_y=CLEAN; "
            "pair_y=Dim1:RESIDENCEAREATYPE_URB,RESIDENCEAREATYPE_RUR; stat_y=slope\n"
            "SUPPORT_IF: difference > 0 AND ci_low > 0\nREJECT_IF: ci_high < 0\nTHREATS: -")
    assert _validated(text)["H3.T1"]["problems"] == []


def test_rules_evaluate_and_missing_outputs_are_undetermined():
    assert evaluate_rule("mean > 0 AND ci_low > 0", {"mean": 0.3, "ci_low": 0.1}) is True
    assert evaluate_rule("ci_high < 0 OR mean < -1", {"ci_high": 0.2, "mean": 0.3}) is False
    assert evaluate_rule("mean > 0", {}) is None
    assert parse_rule("mean >= 0.5")[1] == [("mean", ">=", 0.5)]


def test_untestable_hypothesis_cannot_have_tests():
    tests = validate_plan(parse_plan(PLAN_8B), {"H3": dict(HYPOTHESIS, testable=False)}, AUDIT)
    assert all("not a selected testable hypothesis" in t["problems"][0] for t in tests)


def test_render_round_trips():
    tests = parse_plan(PLAN_8B)
    assert [t["id"] for t in parse_plan(render_plan(tests))] == ["H3.T1", "H3.T2", "H3.T3"]
