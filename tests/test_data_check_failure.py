"""
The data check must never disappear silently.

Background (2026-09-13 run e6cb1ae3): the local 8b model broke the nested
JSON while checking five questions at once. The check returned early,
skipped the "[Data check ...]" label, and three questions needing variables
absent from WHO GHO reached the user showing only the model's own
"Feasibility: Yes". The check now asks for plain-text lines per question
(far harder to break than nested JSON), always labels every question, and
records when it ran on a local model.
"""
from unittest.mock import MagicMock, patch

from agents.gap_analysis import GapAnalysisAgent, _parse_compliance_text
from tools.dataset_schema import DatasetSchema

CONSTRAINTS = "Scope hard. Reject any research question that widens back out to stove technology design."


def _schema():
    return DatasetSchema(
        url="u", columns={"IndicatorCode"},
        values={"IndicatorCode": {"PHE_HHAIR_PROP_POP_CLEAN_FUELS"}},
        meanings={"PHE_HHAIR_PROP_POP_CLEAN_FUELS":
                  "Proportion of population with primary reliance on clean fuels and technologies for cooking (%)"},
    )


def _rq_block(texts):
    return "\n".join(f"RQ {i}: {t}\n- Feasibility: Yes\n- Novelty: n/a\n- Effort: Low"
                     for i, t in enumerate(texts, 1))


def _agent(check_outputs, api_available=True):
    api = MagicMock()
    api._api_available = api_available
    api.generate.return_value = _rq_block(["Question A", "Question B"])
    api.generate_structured.side_effect = check_outputs
    note_db = MagicMock()
    note_db.get_session.return_value = {"goals": "", "constraints": CONSTRAINTS, "background": ""}
    note_db.get_degradations.return_value = []
    return GapAnalysisAgent(api_model=api, note_db=note_db), note_db


def test_unparseable_check_output_still_labels_every_question():
    """Regression pin for e6cb1ae3: no label disappears when the check can't run."""
    agent, note_db = _agent(check_outputs=["{ broken json", "{ also broken"])
    with patch.object(GapAnalysisAgent, "_load_declared_schema", return_value=_schema()):
        questions = agent.generate_checked_questions("topic", "gap report", [], "sess-1", max_rounds=1)

    assert questions
    assert all(q.feasibility_notes.startswith("[Data check UNCHECKED]") for q in questions)
    assert any(c.args[3] == "critical" and "data_check" in c.args[2]
               for c in note_db.save_degradation.call_args_list)


def test_check_raising_an_exception_still_labels_every_question():
    agent, _ = _agent(check_outputs=RuntimeError("model crashed"))
    with patch.object(GapAnalysisAgent, "_load_declared_schema", return_value=_schema()):
        questions = agent.generate_checked_questions("topic", "gap report", [], "sess-1", max_rounds=1)
    assert all(q.feasibility_notes.startswith("[Data check UNCHECKED]") for q in questions)


def test_plain_text_check_output_is_parsed():
    text = (
        "NEED: clean fuel share | MATCH: PHE_HHAIR_PROP_POP_CLEAN_FUELS\n"
        "**NEED:** fuel stacking rates | **MATCH:** NONE\n"
        "VIOLATES: NONE\n"
    )
    parsed = _parse_compliance_text(text)
    assert parsed["required_variables"] == [
        {"need": "clean fuel share", "matched": "PHE_HHAIR_PROP_POP_CLEAN_FUELS"},
        {"need": "fuel stacking rates", "matched": ""},
    ]
    assert parsed["violated_constraint_quote"] == ""


def test_plain_text_violation_line_is_parsed():
    parsed = _parse_compliance_text(
        "NEED: stove efficiency | MATCH: NONE\n"
        "VIOLATES: Reject any research question that widens back out to stove technology design."
    )
    assert parsed["violated_constraint_quote"].startswith("Reject any research question")


def test_each_question_is_checked_in_its_own_call():
    ok = "NEED: clean fuel share | MATCH: PHE_HHAIR_PROP_POP_CLEAN_FUELS\nVIOLATES: NONE"
    agent, _ = _agent(check_outputs=[ok, ok])
    with patch.object(GapAnalysisAgent, "_load_declared_schema", return_value=_schema()):
        questions = agent.generate_checked_questions("topic", "gap report", [], "sess-1", max_rounds=1)
    assert agent._api.generate_structured.call_count == 2
    assert all(q.feasibility_notes.startswith("[Data check PASS]") for q in questions)


def test_gate_running_on_a_local_model_is_recorded():
    ok = "NEED: clean fuel share | MATCH: PHE_HHAIR_PROP_POP_CLEAN_FUELS\nVIOLATES: NONE"
    agent, note_db = _agent(check_outputs=[ok, ok], api_available=False)
    with patch.object(GapAnalysisAgent, "_load_declared_schema", return_value=_schema()):
        agent.generate_checked_questions("topic", "gap report", [], "sess-1", max_rounds=1)
    assert any("local model" in c.args[4] for c in note_db.save_degradation.call_args_list)


def test_question_parsing_strips_markdown_labels():
    """e6cb1ae3 displayed '**RQ:** What ...' and 'Feasibility: ** Yes'."""
    raw = ("RQ 1: **RQ:** What distinguishes rising countries?\n"
           "- **Feasibility:** ** Yes, with GHO data.\n"
           "- **Novelty:** ** Built on UNCERTAIN (x).\n")
    q = GapAnalysisAgent._parse_questions(raw)[0]
    assert q.text == "What distinguishes rising countries?"
    assert q.feasibility_notes == "Yes, with GHO data."
    assert q.novelty_notes == "Built on UNCERTAIN (x)."
