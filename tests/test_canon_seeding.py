"""
Regression tests for canon-seeding (agents/paper_collection.py + tools/semantic_scholar.py).

Background: a 2026-09-12 audit found the agent's arXiv keyword search had
ZERO overlap with the 28-paper bibliography of an actual expert-written
paper in an adjacent subfield, because keyword/recency search structurally
misses highly-cited foundational work. Canon-seeding supplements it with a
citation-count-sorted Semantic Scholar search and guarantees those papers
survive the top-K truncation. These tests pin the merge/truncation logic and
graceful degradation; no real network calls are made.
"""
from unittest.mock import patch

from tools.arxiv_fetcher import PaperRecord
from agents.paper_collection import PaperCollectionAgent


def _paper(aid, title):
    return PaperRecord(arxiv_id=aid, title=title, authors=["A"], year=2023, url="", abstract="x")


def test_merge_canon_adds_a_paper_keyword_search_missed():
    all_papers = [_paper("1111.1111", "Some Recent Paper")]
    canon = [_paper("1706.03762", "Attention Is All You Need")]

    merged, canon_ids = PaperCollectionAgent._merge_canon(all_papers, canon)

    assert len(merged) == 2
    assert "1706.03762" in canon_ids


def test_merge_canon_dedupes_by_arxiv_id():
    all_papers = [_paper("1706.03762", "Attention Is All You Need")]
    canon = [_paper("1706.03762", "Attention Is All You Need")]

    merged, canon_ids = PaperCollectionAgent._merge_canon(all_papers, canon)

    assert len(merged) == 1  # no duplicate row
    assert "1706.03762" in canon_ids  # still flagged as must-include


def test_merge_canon_dedupes_by_normalized_title_when_ids_differ():
    """Semantic Scholar entries without an arXiv match get a synthetic s2: id —
    must still dedupe against an arXiv-search hit of the same paper."""
    all_papers = [_paper("1706.03762", "Attention Is All You Need")]
    canon = [_paper("s2:abc123", "attention is all you need")]  # same title, different case/id

    merged, canon_ids = PaperCollectionAgent._merge_canon(all_papers, canon)

    assert len(merged) == 1
    assert "1706.03762" in canon_ids
    assert "s2:abc123" not in canon_ids


class _StubEmbed:
    is_loaded = True

    def embed(self, text):
        return [0.0] * 8


class _StubVectorDB_AlwaysEmpty:
    """Mirrors ui/runner.py's _DummyVectorDB, which always returns [] from
    query() — the actual production path for every session run through the
    Web UI. Ranking degrades to arrival order in that path."""

    def query(self, query_embedding, n_results):
        return []


def _bare_agent(top_k):
    agent = PaperCollectionAgent.__new__(PaperCollectionAgent)  # skip __init__, no real deps
    agent._embed = _StubEmbed()
    agent._vdb = _StubVectorDB_AlwaysEmpty()
    agent._top_k = top_k
    agent._deg = None  # __init__ normally sets this; see agents/degradation.py
    return agent


def test_canon_paper_survives_topk_truncation_even_when_ranked_last():
    agent = _bare_agent(top_k=3)
    regular = [_paper(f"200{i}.0000{i}", f"Regular Paper {i}") for i in range(5)]
    canon_paper = _paper("1706.03762", "Attention Is All You Need")
    all_papers = regular + [canon_paper]  # canon paper arrives last

    top = agent._select_top_k("topic", all_papers, must_include_ids={"1706.03762"})

    assert any(p.arxiv_id == "1706.03762" for p in top), "canon paper was truncated away"
    assert len(top) == 3


def test_canon_budget_expands_when_more_canon_papers_than_topk():
    agent = _bare_agent(top_k=2)
    canon_ids = {"1706.03762", "1512.03385", "1706.03762x"}
    all_papers = [
        _paper("1706.03762", "Attention Is All You Need"),
        _paper("1512.03385", "Deep Residual Learning"),
        _paper("1706.03762x", "Third Canon Paper"),
        _paper("9999.99999", "Irrelevant Recent Paper"),
    ]

    top = agent._select_top_k("topic", all_papers, must_include_ids=canon_ids)

    assert canon_ids.issubset({p.arxiv_id for p in top})


def test_fetch_canonical_degrades_gracefully_on_network_failure():
    agent = PaperCollectionAgent.__new__(PaperCollectionAgent)
    agent._deg = None
    with patch(
        "tools.semantic_scholar.SemanticScholarFetcher.search_top_cited",
        side_effect=RuntimeError("simulated network failure"),
    ):
        result = agent._fetch_canonical("some topic")

    assert result == []  # must not raise / must not block Phase 1
