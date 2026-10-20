"""
Tests for per-source pacing and 7-day blocks (tools/rate_limit.py,
tools/sources/_http.py, tools/arxiv_fetcher.py).

Background: arXiv blocked this machine on 2026-09-13 after the pipeline sent
requests 3 s apart with library-level retries, and SelfBugFix re-ran the
whole phase on failure. Pacing is now 20-30 s per source, and a throttled
source is blocked for a week instead of retried.
"""
import io
import shutil
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.rate_limit import RateLimiter, SourceBlocked, is_rate_limit_status


class _Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def _limiter(clock, tmp_dir):
    return RateLimiter(db_path=Path(tmp_dir) / "rl.db", min_interval=20, max_interval=30,
                       block_days=7, now=clock.now, sleep=clock.sleep)


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_first_request_does_not_wait(tmp_dir):
    clock = _Clock()
    _limiter(clock, tmp_dir).acquire("arxiv")
    assert clock.slept == []


def test_back_to_back_requests_are_spaced_20_to_30_seconds(tmp_dir):
    clock = _Clock()
    rl = _limiter(clock, tmp_dir)
    rl.acquire("arxiv")
    rl.acquire("arxiv")
    rl.acquire("arxiv")
    assert len(clock.slept) == 2
    assert all(20 <= s <= 30 for s in clock.slept)


def test_different_sources_do_not_wait_on_each_other(tmp_dir):
    clock = _Clock()
    rl = _limiter(clock, tmp_dir)
    rl.acquire("arxiv")
    rl.acquire("europepmc")
    assert clock.slept == []


def test_pacing_persists_across_instances(tmp_dir):
    """A second process (e.g. CLI next to the Web UI) must honour the same spacing."""
    clock = _Clock()
    _limiter(clock, tmp_dir).acquire("arxiv")
    _limiter(clock, tmp_dir).acquire("arxiv")
    assert len(clock.slept) == 1 and 20 <= clock.slept[0] <= 30


def test_blocked_source_raises_without_waiting(tmp_dir):
    clock = _Clock()
    rl = _limiter(clock, tmp_dir)
    rl.block("arxiv", "HTTP 429")
    with pytest.raises(SourceBlocked):
        rl.acquire("arxiv")
    assert clock.slept == []


def test_block_lasts_seven_days_then_clears(tmp_dir):
    clock = _Clock()
    rl = _limiter(clock, tmp_dir)
    rl.block("arxiv", "HTTP 429")

    clock.t += 7 * 86400 - 60
    with pytest.raises(SourceBlocked):
        rl.acquire("arxiv")

    clock.t += 120
    rl.acquire("arxiv")  # no longer blocked


def test_block_persists_across_instances(tmp_dir):
    clock = _Clock()
    _limiter(clock, tmp_dir).block("openalex", "HTTP 429")
    with pytest.raises(SourceBlocked):
        _limiter(clock, tmp_dir).acquire("openalex")


def test_rate_limit_status_rules():
    assert is_rate_limit_status("europepmc", 429)
    assert is_rate_limit_status("arxiv", 503)       # arXiv throttles with 503
    assert not is_rate_limit_status("crossref", 503)
    assert not is_rate_limit_status("arxiv", 404)


def test_http_429_blocks_the_source_and_is_not_retried(tmp_dir):
    from tools.sources import _http

    clock = _Clock()
    rl = _limiter(clock, tmp_dir)
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO())

    with patch.object(_http, "get_limiter", return_value=rl), \
         patch.object(_http.urllib.request, "urlopen", fake_urlopen):
        with pytest.raises(SourceBlocked):
            _http.request_json("europepmc", "https://example.org/search?q=x")
        with pytest.raises(SourceBlocked):
            _http.request_json("europepmc", "https://example.org/search?q=y")

    assert len(calls) == 1  # the second call never reached the network
    assert rl.blocked_until("europepmc") > clock.t


def test_arxiv_search_uses_no_library_retries_and_blocks_on_503(tmp_dir):
    import arxiv
    from tools import arxiv_fetcher

    clock = _Clock()
    rl = _limiter(clock, tmp_dir)
    seen_clients = []

    class FakeClient:
        def __init__(self, **kw):
            seen_clients.append(kw)

        def results(self, search):
            raise arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 503)

    with patch.object(arxiv_fetcher, "get_limiter", return_value=rl), \
         patch.object(arxiv, "Client", FakeClient):
        with pytest.raises(SourceBlocked):
            arxiv_fetcher.ArxivFetcher().search("cooking fuels")

    assert seen_clients[0]["num_retries"] == 0
    assert rl.blocked_until("arxiv") > clock.t
