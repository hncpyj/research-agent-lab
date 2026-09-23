"""
No test may touch the real research database.

Twice in one day a new test wrote into `data/db/research.db` — once because
`NoteDB`'s default path was bound at import time, and once because a fixture
patched the access token but not the storage paths. Both times the test passed
and the damage was only visible afterwards, in the user's own session list.

So isolation stops being something each test remembers to do. Every test runs
with the data directory pointed at its own temporary folder; a test that truly
needs the real one has to say so with `@pytest.mark.real_data`.
"""
from pathlib import Path

import pytest

import config as project_config

_REAL = {name: getattr(project_config, name) for name in
         ("BASE_DIR", "DATA_DIR", "PAPERS_DIR", "DB_DIR", "DATASETS_DIR",
          "EXPERIMENTS_DIR", "CHROMA_PATH", "SQLITE_PATH")}


@pytest.fixture(autouse=True)
def _isolated_storage(request, tmp_path, monkeypatch):
    """Point every storage path at this test's own folder."""
    if request.node.get_closest_marker("real_data"):
        yield
        return

    root = tmp_path / "data"
    monkeypatch.setattr(project_config, "DATA_DIR", root)
    monkeypatch.setattr(project_config, "PAPERS_DIR", root / "papers")
    monkeypatch.setattr(project_config, "DB_DIR", root / "db")
    monkeypatch.setattr(project_config, "DATASETS_DIR", root / "datasets")
    monkeypatch.setattr(project_config, "CHROMA_PATH", root / "db" / "chroma")
    monkeypatch.setattr(project_config, "SQLITE_PATH", root / "db" / "research.db")
    monkeypatch.setattr(project_config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    # Nothing here reaches a real source, so there is nothing to pace. Left at
    # the real 20-30 s the suite spends minutes asleep; a test that wants to
    # check pacing passes its own intervals to RateLimiter.
    monkeypatch.setattr(project_config, "REQUEST_INTERVAL_MIN_S", 0.0)
    monkeypatch.setattr(project_config, "REQUEST_INTERVAL_MAX_S", 0.0)
    for path in (root / "papers", root / "db", root / "datasets", tmp_path / "experiments"):
        path.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture(autouse=True)
def _the_real_database_is_untouched(request):
    """A last line: if a test wrote to the real database, say so at once."""
    if request.node.get_closest_marker("real_data"):
        yield
        return

    real = Path(_REAL["SQLITE_PATH"])
    before = real.stat().st_mtime_ns if real.exists() else None
    yield
    after = real.stat().st_mtime_ns if real.exists() else None
    assert before == after, (
        f"This test wrote to the real database at {real}. Tests must use the "
        "isolated storage fixture; mark it with @pytest.mark.real_data only if "
        "touching real data is genuinely the point."
    )


@pytest.fixture(autouse=True)
def _no_sockets(request, monkeypatch):
    """
    A test never reaches a server, not even a local one.

    The suite was quietly asking Ollama on localhost:11434 whether it was
    there. When it was running the answer came back at once; when it was not,
    every attempt sat for two seconds and the suite took minutes instead of
    seconds. Either way the result depended on what happened to be running on
    the machine, which is not something a test may depend on. Refusing the
    connection is what an absent server does anyway, so the code under test
    sees nothing new -- only sooner, and always.
    """
    if request.node.get_closest_marker("real_network"):
        yield
        return

    import http.client
    import socket

    def refused(address, *args, **kwargs):
        raise ConnectionRefusedError(
            f"Tests do not open connections ({address}). Mock the client, or "
            "mark the test with @pytest.mark.real_network.")

    # The two doors every HTTP client here goes through. Raw sockets are left
    # alone on purpose: asyncio's own wake-up pipe is a loopback socket on
    # Windows, and closing that door stops the test client working.
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(http.client.HTTPConnection, "connect",
                        lambda self: refused((self.host, self.port)))
    yield


def pytest_configure(config):        # pytest passes its own config object here
    config.addinivalue_line(
        "markers", "real_data: this test deliberately uses the real data folder")
    config.addinivalue_line(
        "markers", "real_network: this test deliberately opens a connection")
    config.addinivalue_line(
        "markers", "real_model: this test asks a real model to generate something")
