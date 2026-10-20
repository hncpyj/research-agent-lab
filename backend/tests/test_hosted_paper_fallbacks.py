"""Hosted paper discovery must work without pretending Railway has local models."""

from unittest.mock import MagicMock

import config
from agents.paper_collection import PaperCollectionAgent
from tools.arxiv_fetcher import PaperRecord
from ui.runner import SessionRunner, _APIKeywordModel, _UnavailableEmbed


TOPIC = (
    "Oversight reliability in autonomous AI research agents: human approval, "
    "information separation, provenance, and monitoring failure modes"
)


class _DegradationLog:
    def __init__(self):
        self.records = []

    def record(self, phase, component, severity, message):
        self.records.append((phase, component, severity, message))


def _paper(identifier: str, title: str, abstract: str) -> PaperRecord:
    return PaperRecord(
        arxiv_id=identifier,
        title=title,
        authors=["A"],
        year=2025,
        url="",
        abstract=abstract,
    )


def _bare_agent(*, keyword_model=None, lexical=True):
    agent = PaperCollectionAgent.__new__(PaperCollectionAgent)
    agent._local = None
    agent._keyword_model = keyword_model
    agent._embed = _UnavailableEmbed()
    agent._vdb = MagicMock()
    agent._top_k = 20
    agent._allow_lexical_ranking = lexical
    agent._last_ranking_backend = ""
    agent._deg = _DegradationLog()
    return agent


def test_hosted_mode_skips_ollama_and_gguf_discovery(monkeypatch):
    monkeypatch.setattr(config, "HOSTED", True)
    runner = SessionRunner("session")
    api_model = MagicMock()

    assert runner._configure_local_fallback(api_model) is False
    api_model.set_local_model.assert_not_called()
    event = runner.get_event()
    assert "intentionally disabled" in event["data"]["message"]


def test_self_hosted_mode_keeps_ollama_fallback(monkeypatch):
    import models.ollama_model as ollama_module

    class _Ollama:
        _resolved_model = "local-test"

        def load(self):
            return None

    monkeypatch.setattr(config, "HOSTED", False)
    monkeypatch.setattr(ollama_module, "OllamaModel", _Ollama)
    runner = SessionRunner("session")
    api_model = MagicMock()

    assert runner._configure_local_fallback(api_model) is True
    assert isinstance(api_model.set_local_model.call_args.args[0], _Ollama)


def test_api_keyword_adapter_uses_the_remote_model_task():
    api_model = MagicMock()
    api_model.generate.return_value = '["one", "two", "three"]'

    result = _APIKeywordModel(api_model).generate("prompt", temperature=0.1)

    assert result == '["one", "two", "three"]'
    kwargs = api_model.generate.call_args.kwargs
    assert kwargs["task_type"].name == "KEYWORD_EXTRACTION"
    assert kwargs["max_tokens"] == 300


def test_keyword_fallback_is_short_distinct_and_not_repeated_topic_prefixes():
    keywords = _bare_agent(keyword_model=None)._extract_keywords(TOPIC)

    assert len(keywords) == 3
    assert len({keyword.casefold() for keyword in keywords}) == 3
    assert all(len(keyword.split()) <= 10 for keyword in keywords)
    assert all(len(keyword) <= 80 for keyword in keywords)
    assert len({keyword[:50] for keyword in keywords}) > 1


def test_invalid_or_duplicate_model_keywords_are_filled_deterministically():
    model = MagicMock(is_loaded=True)
    model.generate.return_value = '["agent oversight", "agent oversight", ""]'

    keywords = _bare_agent(keyword_model=model)._extract_keywords(TOPIC)

    assert keywords[0] == "agent oversight"
    assert len(keywords) == 3
    assert len(set(keywords)) == 3


def test_embedding_unavailable_uses_tfidf_and_never_fake_vectors():
    agent = _bare_agent()
    papers = [
        _paper("relevant", "Autonomous research-agent oversight", "approval provenance monitoring"),
        _paper("other", "Marine plankton diversity", "ocean salinity ecology"),
    ]

    ranked, scores = agent._rank_all(TOPIC, papers)

    assert ranked[0].arxiv_id == "relevant"
    assert scores is not None and scores[0] > scores[1]
    assert agent._last_ranking_backend == "lexical"
    assert any(record[1] == "ranking_backend" for record in agent._deg.records)
    assert any("no fake embeddings" in record[3] for record in agent._deg.records)


def test_unavailable_embedder_cannot_generate_placeholder_embeddings():
    import pytest

    embedder = _UnavailableEmbed()
    assert embedder.is_loaded is False
    with pytest.raises(RuntimeError, match="no embedding backend"):
        embedder.embed("anything")
