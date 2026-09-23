"""
Tests for reading papers in Phase 2 (agents/literature_review.py,
tools/sources/europepmc.py).

Background: in the Web UI this phase was constructed with local_model=None,
so "reading" each paper meant copying the first three sentences of its
abstract. Gap analysis never saw a stated limitation or future-work sentence.
The phase now uses the loaded local model, prefers full text, keeps only
limitation/future-work quotes that occur word for word in the text, and
records how much of the collection was actually read.
"""
import json
from unittest.mock import MagicMock, patch

from agents.literature_review import LiteratureReviewAgent, _verified_quotes
from tools.arxiv_fetcher import PaperRecord
from tools.sources import europepmc

ABSTRACT = (
    "We study LPG use in rural India. Households kept using firewood alongside LPG. "
    "Our sample is limited to two districts. Future research should test price interventions."
)


def _paper(**kw):
    base = dict(arxiv_id="epmc:MED:1", title="LPG in rural India", authors=[], year=2020,
                url="", abstract=ABSTRACT, source="europepmc")
    base.update(kw)
    return PaperRecord(**base)


def _note_db():
    db = MagicMock()
    db.get_degradations.return_value = []
    return db


def test_quotes_must_occur_verbatim_in_the_text():
    kept, dropped = _verified_quotes(
        ["Our sample is limited to two districts.", "The study lacked a control group entirely."],
        ABSTRACT,
    )
    assert kept == ["Our sample is limited to two districts."]
    assert dropped == 1


def test_model_extraction_keeps_only_verified_quotes():
    local = MagicMock(is_loaded=True)
    local.generate.return_value = json.dumps({
        "method": "Household survey.",
        "findings": "Households stacked firewood with LPG.",
        "limitation_quotes": ["Our sample is limited to two districts.", "Invented limitation sentence here."],
        "future_work_quotes": ["Future research should test price interventions."],
    })
    note_db = _note_db()
    agent = LiteratureReviewAgent(local_model=local, note_db=note_db)
    paper = _paper()

    agent.run([paper], "sess-1")

    assert paper.limitation == "Our sample is limited to two districts."
    assert paper.future_work == "Future research should test price interventions."
    assert paper.findings == "Households stacked firewood with LPG."
    assert paper.text_source == "abstract only"
    components = [(c.args[1], c.args[2], c.args[3]) for c in note_db.save_degradation.call_args_list]
    assert (2, "literature_review", "warn") in components  # abstract-only + dropped quote


def test_running_without_a_model_is_recorded_as_critical():
    note_db = _note_db()
    agent = LiteratureReviewAgent(local_model=None, note_db=note_db)

    agent.run([_paper()], "sess-1")

    assert any(c.args[1:4] == (2, "literature_review", "critical")
               for c in note_db.save_degradation.call_args_list)


def test_open_access_full_text_is_preferred_over_the_abstract():
    local = MagicMock(is_loaded=True)
    local.generate.return_value = json.dumps({
        "limitation_quotes": ["Stacking was self-reported."], "future_work_quotes": [],
    })
    agent = LiteratureReviewAgent(local_model=local, note_db=_note_db())
    paper = _paper(fulltext_id="PMC123")

    with patch.object(europepmc, "fetch_fulltext_sections",
                      return_value={"Limitations": "Stacking was self-reported."}):
        agent.run([paper], "sess-1")

    assert paper.text_source == "full text"
    assert paper.limitation == "Stacking was self-reported."
    assert "LIMITATIONS" in local.generate.call_args.args[0]


def test_summary_carries_stated_limitations_and_future_work_for_every_paper():
    papers = [_paper(arxiv_id=f"p{i}", title=f"Paper {i}", limitation="Limited sample.",
                     future_work="Test prices.", text_source="full text") for i in range(40)]
    summary = LiteratureReviewAgent(local_model=None, note_db=_note_db()).build_context_summary(papers)

    assert summary.count("Limitations stated by the authors") == 40  # none cut off
    assert '"Limited sample."' in summary
    assert len(summary) <= 14_000 * 1.15


def test_europepmc_marks_full_text_only_for_open_access_with_pmcid():
    oa = europepmc._to_record({"id": "1", "source": "MED", "title": "T", "pmcid": "PMC9", "isOpenAccess": "Y"})
    closed = europepmc._to_record({"id": "2", "source": "MED", "title": "T", "pmcid": "PMC8", "isOpenAccess": "N"})
    assert oa.fulltext_id == "PMC9"
    assert closed.fulltext_id == ""


def test_fulltext_sections_extracts_discussion_limitations_and_future_work():
    xml = """<article><body>
      <sec><title>Methods</title><p>Survey design.</p></sec>
      <sec><title>Discussion</title><p>Stacking persisted.</p>
        <sec><title>Limitations</title><p>Self-reported fuel use.</p></sec></sec>
      <sec><title>Conclusions and future work</title><p>Test subsidies.</p></sec>
    </body></article>"""
    with patch.object(europepmc, "request_text", return_value=xml):
        sections = europepmc.fetch_fulltext_sections("PMC1")
    assert "Methods" not in sections
    assert "Self-reported fuel use." in sections["Limitations"]
    assert sections["Conclusions and future work"] == "Test subsidies."
