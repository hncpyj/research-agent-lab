"""
Tests for the data/constraint compliance gate (agents/gap_analysis.py,
tools/dataset_schema.py).

Background: in a 2026-09-13 run every research question said "Feasibility:
Yes", including ones that needed fuel-stacking or intervention variables the
declared WHO GHO download does not contain, and one inside a scope the user
had explicitly excluded. The gate reads the declared dataset's real columns
and values, checks each question's required variables and constraint
violations mechanically, and regenerates rejected questions. No network.
"""
import io
import shutil
import tempfile
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.gap_analysis import (
    GapAnalysisAgent,
    ResearchQuestion,
    _evaluate_compliance,
)
from tools import dataset_schema
from tools.dataset_schema import DatasetSchema, find_dataset_urls, load_schema
from tools.rate_limit import RateLimiter, SourceBlocked

CONSTRAINTS = (
    "Open data only. Scope hard. Reject any research question that widens back out to "
    "indoor air quality in general, to air pollution exposure measurement, or to stove "
    "technology design."
)

LONG_FORMAT_CSV = (
    "IndicatorCode,Location,Period,Dim1,FactValueNumeric\n"
    "PHE_HHAIR_PROP_POP_CLEAN_FUELS,Ghana,2010,Urban,41.2\n"
    "PHE_HHAIR_PROP_POP_CLEAN_FUELS,Ghana,2010,Rural,9.8\n"
    "AIR_42,Ghana,2016,Total,1234\n"
)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _zip_bytes(name, content):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


# --- schema extraction -------------------------------------------------------------

def test_find_dataset_urls_in_brief_text():
    text = ("It is at https://ghobulkdownloads.blob.core.windows.net/ghocontainer/"
            "household-air-pollution.zip. It contains the indicator ...")
    assert find_dataset_urls(text) == [
        "https://ghobulkdownloads.blob.core.windows.net/ghocontainer/household-air-pollution.zip"
    ]


def test_long_format_zip_exposes_indicator_codes_and_dimensions(tmp_dir):
    """Variables in long-format data live in value columns, not headers."""
    url = "https://example.blob.core.windows.net/c/hap.zip"
    cached = tmp_dir / "example.blob.core.windows.net_hap.zip"
    cached.write_bytes(_zip_bytes("hap.csv", LONG_FORMAT_CSV))

    schema = load_schema(url, cache_dir=tmp_dir)

    assert "IndicatorCode" in schema.columns
    vocab = schema.vocabulary()
    assert "phe_hhair_prop_pop_clean_fuels" in vocab
    assert {"urban", "rural"} <= vocab
    assert "FactValueNumeric" not in schema.values  # numeric column: header only


def test_download_is_paced_and_503_from_storage_host_blocks(tmp_dir):
    rl = RateLimiter(db_path=tmp_dir / "rl.db", min_interval=20, max_interval=30,
                     now=lambda: 1_000_000.0, sleep=lambda s: None)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "Server Busy", {}, io.BytesIO())

    with patch.object(dataset_schema, "get_limiter", return_value=rl), \
         patch.object(dataset_schema, "check_url", lambda url: url), \
         patch.object(dataset_schema, "_fetch", fake_urlopen):
        with pytest.raises(SourceBlocked):
            load_schema("https://x.blob.core.windows.net/c/data.zip", cache_dir=tmp_dir)

    assert rl.blocked_until("host:x.blob.core.windows.net") > 1_000_000.0


# --- mechanical evaluation ---------------------------------------------------------------

def _schema():
    return DatasetSchema(
        url="u", files=["hap.csv"],
        columns={"IndicatorCode", "Location", "Period", "Dim1"},
        values={"IndicatorCode": {"PHE_HHAIR_PROP_POP_CLEAN_FUELS", "PHE_HHAIR_POP_POLLUTING_FUELS", "AIR_42"},
                "Dim1": {"Urban", "Rural", "Total"}},
        meanings={
            "PHE_HHAIR_PROP_POP_CLEAN_FUELS": "Proportion of population with primary reliance on clean fuels and technologies for cooking (%)",
            "PHE_HHAIR_POP_POLLUTING_FUELS": "Population with primary reliance on polluting fuels and technologies for cooking (in millions)",
            "AIR_42": "Household air pollution attributable deaths",
        },
    )


def _rq(i, text="q"):
    return ResearchQuestion(index=i, text=text)


def test_question_needing_a_variable_absent_from_the_data_fails():
    """Regression pin: 'impact of fuel stacking' — GHO has no stacking measure."""
    rq = _rq(1)
    _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [
            {"need": "fuel stacking prevalence", "matched": ""},
            {"need": "attributable deaths", "matched": "AIR_42"},
        ],
        "violated_constraint_quote": "",
    }], _schema(), CONSTRAINTS)

    assert rq.compliance == "fail"
    assert "fuel stacking prevalence" in rq.compliance_notes


def test_matched_name_that_is_not_really_in_the_data_fails():
    rq = _rq(1)
    _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [{"need": "intervention efficiency", "matched": "INTERVENTION_EFFICIENCY"}],
        "violated_constraint_quote": "",
    }], _schema(), CONSTRAINTS)
    assert rq.compliance == "fail"


def test_all_variables_present_and_no_violation_passes():
    rq = _rq(1)
    _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [
            {"need": "clean fuel share", "matched": "PHE_HHAIR_PROP_POP_CLEAN_FUELS"},
            {"need": "urban/rural split", "matched": "Urban"},
        ],
        "violated_constraint_quote": "",
    }], _schema(), CONSTRAINTS)
    assert rq.compliance == "pass"
    assert "PHE_HHAIR_PROP_POP_CLEAN_FUELS" in rq.compliance_notes


def test_real_constraint_quote_fails_the_question():
    rq = _rq(1)
    _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [{"need": "clean fuel share", "matched": "PHE_HHAIR_PROP_POP_CLEAN_FUELS"}],
        "violated_constraint_quote": "Reject any research question that widens back out to indoor air quality in general, to air pollution exposure measurement, or to stove technology design.",
    }], _schema(), CONSTRAINTS)
    assert rq.compliance == "fail"
    assert "violates constraint" in rq.compliance_notes


def test_fabricated_constraint_quote_is_ignored_and_reported():
    rq = _rq(1)
    fabricated = _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [{"need": "clean fuel share", "matched": "PHE_HHAIR_PROP_POP_CLEAN_FUELS"}],
        "violated_constraint_quote": "Do not study urban areas.",
    }], _schema(), CONSTRAINTS)
    assert rq.compliance == "pass"
    assert fabricated


def test_empty_variable_list_fails_rather_than_passing_by_default():
    rq = _rq(1)
    _evaluate_compliance([rq], [{"index": 1, "required_variables": [], "violated_constraint_quote": ""}],
                         _schema(), CONSTRAINTS)
    assert rq.compliance == "fail"


def test_without_a_schema_only_constraints_are_checked():
    rq = _rq(1)
    _evaluate_compliance([rq], [{"index": 1, "required_variables": [], "violated_constraint_quote": ""}],
                         None, CONSTRAINTS)
    assert rq.compliance == "pass"
    assert "not checked" in rq.compliance_notes


# --- gate with regeneration -----------------------------------------------------------------

def _rq_block(texts):
    return "\n".join(f"RQ {i}: {t}\n- Feasibility: Yes\n- Novelty: n/a\n- Effort: Low"
                     for i, t in enumerate(texts, 1))


# One plain-text reply per question checked (see _COMPLIANCE_PROMPT).
PASS_REPLY = "NEED: clean fuel share | MATCH: PHE_HHAIR_PROP_POP_CLEAN_FUELS\nVIOLATES: NONE"
FAIL_REPLY = "NEED: fuel stacking | MATCH: NONE\nVIOLATES: NONE"


def _agent(generate_outputs, compliance_outputs):
    api = MagicMock()
    api.generate.side_effect = generate_outputs
    api.generate_structured.side_effect = compliance_outputs
    note_db = MagicMock()
    note_db.get_session.return_value = {"goals": "", "constraints": CONSTRAINTS, "background": ""}
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)
    return agent, api, note_db


def test_rejected_questions_are_regenerated_and_never_shown():
    agent, api, _ = _agent(
        generate_outputs=[
            _rq_block(["Trajectory question A", "Stacking impact question", "Intervention efficiency question"]),
            _rq_block(["Trajectory question B", "Trajectory question C"]),
        ],
        compliance_outputs=[PASS_REPLY, FAIL_REPLY, FAIL_REPLY, PASS_REPLY, PASS_REPLY],
    )
    with patch.object(GapAnalysisAgent, "_load_declared_schema", return_value=_schema()):
        questions = agent.generate_checked_questions("topic", "gap report", [], "sess-1")

    texts = [q.text for q in questions]
    assert texts == ["Trajectory question A", "Trajectory question B", "Trajectory question C"]
    assert [q.index for q in questions] == [1, 2, 3]
    assert all(q.feasibility_notes.startswith("[Data check PASS]") for q in questions)
    second_prompt = api.generate.call_args_list[1].kwargs["prompt"]
    assert "Stacking impact question" in second_prompt  # told what not to repeat


def test_when_nothing_passes_the_last_round_is_shown_with_reasons():
    agent, _, note_db = _agent(
        generate_outputs=[_rq_block(["Stacking question"])] * 2,
        compliance_outputs=[FAIL_REPLY] * 2,
    )
    with patch.object(GapAnalysisAgent, "_load_declared_schema", return_value=_schema()):
        questions = agent.generate_checked_questions("topic", "gap report", [], "sess-1", max_rounds=2)

    assert questions[0].compliance == "fail"
    assert questions[0].feasibility_notes.startswith("[Data check FAIL]")
    assert any(c.args[1:4] == (3, "data_check", "critical")
               for c in note_db.save_degradation.call_args_list)


def test_check_that_cannot_run_marks_questions_unchecked():
    api = MagicMock()
    api.generate.return_value = _rq_block(["Some question"])
    api.generate_structured.return_value = "not json"
    note_db = MagicMock()
    note_db.get_session.return_value = {"goals": "", "constraints": CONSTRAINTS, "background": ""}
    agent = GapAnalysisAgent(api_model=api, note_db=note_db)

    with patch.object(GapAnalysisAgent, "_load_declared_schema", return_value=None):
        questions = agent.generate_checked_questions("topic", "gap report", [], "sess-1")

    assert questions[0].compliance == "unchecked"


# --- semantic mapping check (2026-09-13 a02769dd regression) ------------------------------

def _fake_similarity(need, meaning):
    """Scores measured with nomic-embed-text on the real WHO GHO meanings."""
    table = {
        ("fuel stacking rates", "Population with primary reliance on polluting fuels and technologies for cooking (in millions)"): 0.530,
        ("clean fuel share", "Proportion of population with primary reliance on clean fuels and technologies for cooking (%)"): 0.597,
    }
    return table[(need, meaning)]


def test_existing_code_mapped_to_the_wrong_need_fails():
    """Regression pin: the only question shown in a02769dd needed 'fuel stacking rates'
    and passed because the model mapped it to a real, unrelated indicator code."""
    rq = _rq(1)
    _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [{"need": "fuel stacking rates", "matched": "PHE_HHAIR_POP_POLLUTING_FUELS"}],
        "violated_constraint_quote": "",
    }], _schema(), CONSTRAINTS, similarity=_fake_similarity)
    assert rq.compliance == "fail"
    assert "does not measure it" in rq.compliance_notes


def test_correct_code_mapping_passes_the_semantic_check():
    rq = _rq(1)
    _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [{"need": "clean fuel share", "matched": "PHE_HHAIR_PROP_POP_CLEAN_FUELS"}],
        "violated_constraint_quote": "",
    }], _schema(), CONSTRAINTS, similarity=_fake_similarity)
    assert rq.compliance == "pass"
    assert "Proportion of population" in rq.compliance_notes


def test_column_name_mapping_is_accepted_but_marked_unchecked():
    rq = _rq(1)
    _evaluate_compliance([rq], [{
        "index": 1,
        "required_variables": [{"need": "country", "matched": "Location"}],
        "violated_constraint_quote": "",
    }], _schema(), CONSTRAINTS, similarity=lambda a, b: 0.0)
    assert rq.compliance == "pass"
    assert "not semantically checked" in rq.compliance_notes


def test_code_tables_become_meanings_not_data_columns(tmp_dir):
    url = "https://example.blob.core.windows.net/c/hap2.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("codes/GHO.csv", "Dimension,Code,Title\n"
                                     "GHO,AIR_11,Household air pollution attributable deaths\n"
                                     "GHO,UNUSED_1,Never used\n")
        zf.writestr("data/AIR_11.csv", "IndicatorCode,SpatialDimensionValueCode,NumericValue\n"
                                       "AIR_11,GHA,12\n")
    (tmp_dir / "example.blob.core.windows.net_hap2.zip").write_bytes(buf.getvalue())

    schema = load_schema(url, cache_dir=tmp_dir)

    assert "Title" not in schema.columns
    assert schema.meaning_of("AIR_11") == "Household air pollution attributable deaths"
    described = schema.describe()
    assert "AIR_11: Household air pollution attributable deaths" in described
    assert "UNUSED_1" not in described  # defined but never occurs in the data


def test_large_code_groups_are_summarized():
    schema = DatasetSchema(url="u", columns={"Country"},
                           values={"Country": {f"C{i:03d}" for i in range(120)}},
                           meanings={f"C{i:03d}": f"Country {i}" for i in range(120)})
    described = schema.describe()
    assert "120 codes, e.g." in described
    assert described.count("Country ") < 10
