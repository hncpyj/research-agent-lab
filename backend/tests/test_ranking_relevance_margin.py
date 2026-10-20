"""
Regression tests for numpy-based paper ranking and the relative relevance
margin (agents/paper_collection.py).

Background: a 2026-09-12 test session found Phase 1 returning a
30%-precision paper set (6 of 20 relevant). `_rank_all` delegated to
`self._vdb.query()`, and the Web UI's `_DummyVectorDB.query()` always
returns `[]`, which silently left papers in the sources' own result order.

_rank_all now computes cosine similarity directly, and _select_top_k keeps
only papers within RELEVANCE_MARGIN of the best score. An absolute floor was
tried first and replaced: re-ranking that session's 20 papers with
nomic-embed-text gave every paper >= 0.405, so an absolute 0.35 floor
removed nothing, while relative to the top score (0.758) the 6 relevant
papers (>= 0.681) separated cleanly from the best off-topic one (0.601).
"""
import math
from unittest.mock import MagicMock

from tools.arxiv_fetcher import PaperRecord
from agents.paper_collection import PaperCollectionAgent
import config


def _paper(aid, title):
    return PaperRecord(arxiv_id=aid, title=title, authors=["A"], year=2023, url="", abstract="x")


class _FakeDeg:
    def __init__(self):
        self.records = []

    def record(self, phase, component, severity, message):
        self.records.append((phase, component, severity, message))


class _ScoredEmbed:
    """Embeds the topic as [1, 0] and each paper at a chosen cosine to it."""
    is_loaded = True

    def __init__(self, score_by_title):
        self._scores = score_by_title

    def embed(self, text):
        if text == "topic":
            return [1.0, 0.0]
        title = text.split("\n", 1)[0]
        s = self._scores[title]
        return [s, math.sqrt(1 - s * s)]


class _ZeroEmbed:
    """Stands in for the Web UI's old always-zero dummy embedder."""
    is_loaded = True

    def embed(self, text):
        return [0.0, 0.0]


def _agent(embed_model, top_k=20, deg=None):
    agent = PaperCollectionAgent.__new__(PaperCollectionAgent)
    agent._embed = embed_model
    agent._vdb = MagicMock()  # must NOT be queried by the ranking path
    agent._top_k = top_k
    agent._deg = deg
    return agent


def test_rank_all_never_queries_the_vector_db():
    agent = _agent(_ScoredEmbed({"a": 0.9, "b": 0.1}))
    agent._rank_all("topic", [_paper("1", "a"), _paper("2", "b")])
    agent._vdb.query.assert_not_called()


def test_higher_similarity_ranks_first():
    agent = _agent(_ScoredEmbed({"low": 0.2, "high": 0.8}))
    ranked, sims = agent._rank_all("topic", [_paper("1", "low"), _paper("2", "high")])
    assert ranked[0].arxiv_id == "2"
    assert sims[0] > sims[1]


def test_margin_reproduces_the_2026_09_12_session():
    """The measured scores from the real session: 6 relevant, 14 off-topic."""
    relevant = [0.758, 0.722, 0.719, 0.688, 0.682, 0.681]
    off_topic = [0.601, 0.580, 0.573, 0.567, 0.554, 0.550, 0.524,
                 0.517, 0.516, 0.506, 0.499, 0.484, 0.453, 0.405]
    scores = {f"rel{i}": s for i, s in enumerate(relevant)}
    scores.update({f"off{i}": s for i, s in enumerate(off_topic)})
    papers = [_paper(t, t) for t in scores]
    deg = _FakeDeg()
    agent = _agent(_ScoredEmbed(scores), top_k=20, deg=deg)

    top = agent._select_top_k("topic", papers)

    assert sorted(p.arxiv_id for p in top) == sorted(f"rel{i}" for i in range(6))
    assert any(r[1] == "relevance_margin" and r[2] == "warn" for r in deg.records)


def test_margin_is_relative_to_the_top_score_not_absolute():
    """The same gaps shifted down by 0.4 must keep the same papers."""
    scores = {"best": 0.40, "close": 0.33, "far": 0.20}
    agent = _agent(_ScoredEmbed(scores), top_k=20)
    top = agent._select_top_k("topic", [_paper(t, t) for t in scores])
    assert {p.arxiv_id for p in top} == {"best", "close"}


def test_canon_papers_are_exempt_from_the_margin():
    scores = {"canon": 0.10, "best": 0.90, "close": 0.85}
    agent = _agent(_ScoredEmbed(scores), top_k=5)
    top = agent._select_top_k("topic", [_paper(t, t) for t in scores], must_include_ids={"canon"})
    assert any(p.arxiv_id == "canon" for p in top)


def test_canon_papers_do_not_set_the_cutoff():
    """A canon paper scoring above everything must not push regular papers out."""
    scores = {"canon": 0.99, "best": 0.70, "close": 0.65}
    agent = _agent(_ScoredEmbed(scores), top_k=5)
    top = agent._select_top_k("topic", [_paper(t, t) for t in scores], must_include_ids={"canon"})
    assert {p.arxiv_id for p in top} == {"canon", "best", "close"}


def test_degenerate_zero_embedding_is_recorded_as_critical_not_silently_ranked():
    deg = _FakeDeg()
    agent = _agent(_ZeroEmbed(), deg=deg)
    papers = [_paper("1", "paper one"), _paper("2", "paper two")]

    ranked, sims = agent._rank_all("topic", papers)

    assert sims is None
    assert ranked == papers
    assert any(r[1] == "ranking" and r[2] == "critical" for r in deg.records)


def test_relevance_margin_is_configurable():
    assert isinstance(config.RELEVANCE_MARGIN, float)
    assert 0.0 < config.RELEVANCE_MARGIN < 1.0
