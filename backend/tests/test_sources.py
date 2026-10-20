"""
Tests for the multi-source paper search (tools/sources).

Spreading searches across independent sources keeps any one of them from
carrying the full request load, and lets a blocked or unconfigured source
reduce coverage instead of emptying the collection. No network calls — each
source's JSON parsing is tested on recorded response shapes.
"""
from unittest.mock import patch

import tools.sources as sources
from tools.arxiv_fetcher import PaperRecord
from tools.rate_limit import SourceBlocked
from tools.sources import crossref, europepmc, openalex, openreview
from tools.sources._http import SourceUnavailable


def _p(pid, title, doi="", source="arxiv"):
    return PaperRecord(arxiv_id=pid, title=title, authors=[], year=2020, url="",
                       abstract="", doi=doi, source=source)


# --- parsing -----------------------------------------------------------------

def test_openalex_rebuilds_abstract_from_inverted_index():
    rec = openalex._to_record({
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1/abc",
        "display_name": "Fuel stacking in Ghana",
        "publication_year": 2019,
        "authorships": [{"author": {"display_name": "A. Author"}}],
        "abstract_inverted_index": {"stacking": [1], "Fuel": [0], "persists": [2]},
        "primary_location": {"landing_page_url": "https://example.org/paper"},
    })
    assert rec.arxiv_id == "openalex:W123"
    assert rec.doi == "10.1/abc"
    assert rec.abstract == "Fuel stacking persists"
    assert rec.source == "openalex"


def test_openalex_without_api_key_is_unavailable_not_called():
    with patch.object(openalex.config, "OPENALEX_API_KEY", ""), \
         patch.object(openalex, "request_json") as req:
        try:
            openalex.search("x", 5)
            assert False, "expected SourceUnavailable"
        except SourceUnavailable:
            pass
        req.assert_not_called()


def test_europepmc_parses_core_result():
    rec = europepmc._to_record({
        "id": "12345", "source": "MED", "doi": "10.2/xyz",
        "title": "Household air pollution and <i>LPG</i> adoption.",
        "authorString": "Smith J, Doe A.", "pubYear": "2021",
        "abstractText": "<h4>Background</h4>LPG adoption stalls.",
    })
    assert rec.arxiv_id == "epmc:MED:12345"
    assert rec.title == "Household air pollution and LPG adoption"
    assert rec.authors == ["Smith J", "Doe A"]
    assert rec.year == 2021
    assert "LPG adoption stalls." in rec.abstract


def test_crossref_skips_items_without_title_or_doi():
    assert crossref._to_record({"DOI": "10.3/q", "title": []}) is None
    rec = crossref._to_record({
        "DOI": "10.3/q", "title": ["Clean cooking finance"],
        "author": [{"given": "Ann", "family": "Lee"}],
        "issued": {"date-parts": [[2018, 4]]},
        "abstract": "<jats:p>Finance lags.</jats:p>",
    })
    assert rec.arxiv_id == "doi:10.3/q"
    assert rec.year == 2018
    assert rec.abstract == "Finance lags."


def test_openreview_requires_credentials():
    with patch.object(openreview.config, "OPENREVIEW_USERNAME", ""), \
         patch.object(openreview, "request_json") as req:
        try:
            openreview.search("x", 5)
            assert False, "expected SourceUnavailable"
        except SourceUnavailable:
            pass
        req.assert_not_called()


def test_openreview_parses_v2_note():
    rec = openreview._to_record({
        "id": "abc", "forum": "abc", "cdate": 1_700_000_000_000,
        "content": {"title": {"value": "A Paper"}, "abstract": {"value": "Text"},
                    "authors": {"value": ["X", "Y"]}},
    })
    assert rec.arxiv_id == "openreview:abc"
    assert rec.year == 2023
    assert rec.authors == ["X", "Y"]


# --- aggregation ---------------------------------------------------------------

def test_search_all_reports_blocked_and_unconfigured_sources_and_keeps_the_rest():
    def ok(query, limit):
        return [_p("epmc:MED:1", "Paper one")]

    def blocked(query, limit):
        raise SourceBlocked("arxiv", 2_000_000_000, "HTTP 429")

    def unconfigured(query, limit):
        raise SourceUnavailable("OPENALEX_API_KEY is not set")

    fake = {"arxiv": blocked, "openalex": unconfigured, "europepmc": ok}
    with patch.dict(sources.SEARCHERS, fake, clear=True):
        papers, problems = sources.search_all("q", 5, sources=["arxiv", "openalex", "europepmc"])

    assert [p.arxiv_id for p in papers] == ["epmc:MED:1"]
    assert set(problems) == {"arxiv", "openalex"}
    assert "blocked" in problems["arxiv"]


def test_deduplicate_merges_the_same_work_found_via_different_sources():
    papers = [
        _p("openalex:W1", "Clean Cooking Transitions", doi="10.9/ABC"),
        _p("epmc:MED:7", "Different title", doi="10.9/abc"),       # same DOI
        _p("doi:10.9/zzz", "clean cooking transitions!"),          # same title
        _p("2101.00001", "Unrelated"),
    ]
    out = sources.deduplicate(papers)
    assert [p.arxiv_id for p in out] == ["openalex:W1", "2101.00001"]


def test_google_scholar_is_not_a_source():
    """No official API and its terms prohibit automated queries."""
    assert not any("scholar.google" in name or name == "google_scholar" for name in sources.SEARCHERS)
