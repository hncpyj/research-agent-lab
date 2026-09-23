"""
Stage S3: hypotheses must map every concept to a variable the data has.

RAW_8B is llama3.1:8b's actual reply for session c5a020c3 on 2026-09-14. It
added "split=..." fields the format does not have; an earlier parser ignored
them and passed H2 (a death rate split only by sex) as split by urban/rural.
"""
from unittest.mock import MagicMock

from agents.hypothesis_design import MAPPING_MIN_SIMILARITY, HypothesisDesigner, _parse

RAW_8B = """Here are 3 hypotheses that answer the research question using only the variables above:
HYPOTHESIS: H1
STATEMENT: Countries with rising clean fuel reliance have higher urban and rural clean fuel shares.
ROW: concept=Clean fuel reliance | variable=PHE_HHAIR_PROP_POP_CLEAN_FUELS | expect=Increasing
ROW: concept=Urban clean fuel share | variable=PHE_HHAIR_PROP_POP_CLEAN_FUELS | split=RESIDENCEAREATYPE_URB | expect=Increasing
CANNOT_TEST: The impact of policies, prices, or income on clean fuel adoption.
HYPOTHESIS: H2
STATEMENT: Countries with rising clean fuel reliance have lower household air pollution attributable death rates.
ROW: concept=Household air pollution attributable death rate | variable=SDGAIRBODA | expect=Decreasing
ROW: concept=Urban household air pollution attributable death rate | variable=SDGAIRBODA | split=RESIDENCEAREATYPE_URB | expect=Decreasing
CANNOT_TEST: none
HYPOTHESIS: H3
STATEMENT: The rate of increase in clean fuel share is slower where attributable death rates are higher.
ROW: concept=Interaction | variable=PHE_HHAIR_PROP_POP_CLEAN_FUELS, SDGAIRBODA | expect=Negative interaction
CANNOT_TEST: none
"""

AREA = [{"code": "RESIDENCEAREATYPE_URB", "meaning": "Urban"}, {"code": "RESIDENCEAREATYPE_RUR", "meaning": "Rural"}]
SEX = [{"code": "SEX_FMLE", "meaning": "Female"}, {"code": "SEX_MLE", "meaning": "Male"}]
AUDIT = {
    "indicators": [
        {"code": "PHE_HHAIR_PROP_POP_CLEAN_FUELS", "meaning": "Proportion ... clean fuels (%)", "unit": "%",
         "splits": {"DisaggregatingDimension1ValueCode": AREA}},
        {"code": "SDGAIRBODA", "meaning": "attributable death rate", "unit": "per 100 000",
         "splits": {"DisaggregatingDimension1ValueCode": SEX}},
    ],
    "groups": {"ParentLocationCode": [{"code": "AFR", "meaning": "Africa"}]},
}


class _Embed:
    """Similarity 0.9 unless the concept names policy, which the data cannot measure."""
    def embed(self, text):
        return [0.0, 1.0] if "policy" in text.lower() else [1.0, 0.3]


def _designer():
    deg = MagicMock()
    return HypothesisDesigner(api_model=MagicMock(), embedder=_Embed(), deg=deg), deg


def test_parser_reads_the_real_8b_reply_including_extra_fields():
    hyps = _parse(RAW_8B)
    assert [h["id"] for h in hyps] == ["H1", "H2", "H3"]
    assert hyps[0]["rows"][1]["extra"] == {"split": "RESIDENCEAREATYPE_URB"}
    assert hyps[1]["cannot_test"] == ""


def test_split_that_the_indicator_does_not_have_makes_the_hypothesis_untestable():
    designer, _ = _designer()
    hyps = {h["id"]: h for h in designer.check(_parse(RAW_8B), AUDIT, [])}
    assert hyps["H1"]["testable"]
    assert hyps["H1"]["rows"][1]["split"] == "DisaggregatingDimension1ValueCode:RESIDENCEAREATYPE_URB"
    assert not hyps["H2"]["testable"]
    assert "no split RESIDENCEAREATYPE_URB" in hyps["H2"]["problems"][0]
    assert not hyps["H3"]["testable"]                          # two codes jammed into one variable


def test_concept_the_data_cannot_measure_is_rejected_by_meaning():
    raw = ("HYPOTHESIS: H1\nSTATEMENT: Stricter energy policy raises clean fuel use.\n"
           "ROW: concept=energy policy stringency | variable=PHE_HHAIR_PROP_POP_CLEAN_FUELS | expect=up\n")
    designer, _ = _designer()
    h = designer.check(_parse(raw), AUDIT, [])[0]
    assert not h["testable"]
    assert "does not match what the variable measures" in h["problems"][0]


def test_standalone_split_row_must_belong_to_one_of_the_hypothesis_indicators():
    raw = ("HYPOTHESIS: H1\nSTATEMENT: Urban and rural death rates differ.\n"
           "ROW: concept=death rate | variable=SDGAIRBODA | expect=differs\n"
           "ROW: concept=urban versus rural | variable=DisaggregatingDimension1ValueCode:RESIDENCEAREATYPE_URB,RESIDENCEAREATYPE_RUR | expect=-\n")
    designer, _ = _designer()
    h = designer.check(_parse(raw), AUDIT, [])[0]
    assert not h["testable"]
    assert "none of this hypothesis' indicators is split by" in h["problems"][-1]


def test_without_an_embedding_model_nothing_is_testable_and_it_is_recorded():
    deg = MagicMock()
    designer = HypothesisDesigner(api_model=MagicMock(), embedder=None, deg=deg)
    hyps = designer.check(_parse(RAW_8B), AUDIT, [])
    assert not any(h["testable"] for h in hyps)
    assert deg.record.call_args.args[:3] == (4, "hypothesis_mapping", "critical")


def test_split_named_in_the_concept_is_attached_and_marked_inferred():
    raw = ("HYPOTHESIS: H1\nSTATEMENT: Rising countries have higher urban shares.\n"
           "ROW: concept=Urban clean fuel share | variable=PHE_HHAIR_PROP_POP_CLEAN_FUELS | expect=higher\n"
           "ROW: concept=Clean fuel reliance trend | variable=PHE_HHAIR_PROP_POP_CLEAN_FUELS | expect=rising\n")
    designer, _ = _designer()
    h = designer.check(_parse(raw), AUDIT, [])[0]
    assert h["rows"][0]["split"] == "DisaggregatingDimension1ValueCode:RESIDENCEAREATYPE_URB"
    assert h["rows"][0]["split_inferred"] is True
    assert "split" not in h["rows"][1]


def test_threshold_is_the_measured_value():
    assert MAPPING_MIN_SIMILARITY == 0.56
