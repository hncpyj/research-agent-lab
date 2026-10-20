"""
What a server serving other people may and may not do.

The pipeline's last phases run code that a model wrote. On the machine of the
person who asked for it, that is the whole point. On a server other people sign
in to, it is remote code execution offered to strangers, and nothing in a
prompt makes it safe.

So the hosted build refuses to execute, loudly and before anything runs, and
answers only to its own hostname. These pin both, because the failure mode of
getting them wrong is not a bad report -- it is someone else's machine.
"""
import pytest
from fastapi.testclient import TestClient

import config


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path / "experiments")
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", False)
    return tmp_path


def _runner():
    from agents.experiment_runner import ExperimentRunnerAgent

    return ExperimentRunnerAgent(api_model=None, note_db=None,
                                 experiments_base_dir=config.EXPERIMENTS_DIR)


def test_generated_experiment_code_is_not_run(hosted):
    from agents.experiment_runner import CodeExecutionDisabled

    with pytest.raises(CodeExecutionDisabled, match="does not run generated code"):
        _runner().run("a-session")


def test_an_assembled_analysis_is_not_run_either(hosted):
    """The assembly is built from fixed scripts, but it still executes here."""
    from agents.experiment_runner import CodeExecutionDisabled

    with pytest.raises(CodeExecutionDisabled, match="does not run analysis code"):
        _runner().run_manifest("a-session", config.EXPERIMENTS_DIR, "h1")


def test_it_says_what_to_do_instead(hosted):
    from agents.experiment_runner import CodeExecutionDisabled

    with pytest.raises(CodeExecutionDisabled) as refused:
        _runner().run("a-session")
    assert "run it on your own" in str(refused.value)


def test_nothing_changes_on_your_own_machine(tmp_path, monkeypatch):
    """The refusal must depend on the setting, not on being in a test."""
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    monkeypatch.setattr(config, "EXPERIMENTS_DIR", tmp_path)
    from agents.experiment_runner import CodeExecutionDisabled

    with pytest.raises(Exception) as raised:
        _runner().run("a-session")
    assert not isinstance(raised.value, CodeExecutionDisabled)     # it got past the gate


def test_hosting_turns_execution_off_by_default(monkeypatch):
    """Reading config with HOSTED=1 must not leave execution on."""
    import importlib

    monkeypatch.setenv("HOSTED", "1")
    monkeypatch.delenv("ALLOW_CODE_EXECUTION", raising=False)
    fresh = importlib.reload(config)
    try:
        assert fresh.HOSTED is True
        assert fresh.ALLOW_CODE_EXECUTION is False
    finally:
        monkeypatch.delenv("HOSTED", raising=False)
        importlib.reload(config)


def test_a_host_can_still_choose_to_allow_it(monkeypatch):
    import importlib

    monkeypatch.setenv("HOSTED", "1")
    monkeypatch.setenv("ALLOW_CODE_EXECUTION", "1")
    fresh = importlib.reload(config)
    try:
        assert fresh.ALLOW_CODE_EXECUTION is True
    finally:
        monkeypatch.delenv("HOSTED", raising=False)
        monkeypatch.delenv("ALLOW_CODE_EXECUTION", raising=False)
        importlib.reload(config)


# --- the door ---------------------------------------------------------------------

def test_a_request_for_another_hostname_is_refused(tmp_path):
    """
    The allow-list is read when the app is built, so this is checked in a fresh
    process: adding the middleware to the already-running app under test would
    prove nothing about what a deployed server does.
    """
    import os
    import subprocess
    import sys

    script = (
        "import os, config, importlib\n"
        "from fastapi.testclient import TestClient\n"
        "import ui.app as ui_app\n"
        "c = TestClient(ui_app.app)\n"
        "print(c.get('/health', headers={'host': 'somewhere-else.example'}).status_code,\n"
        "      c.get('/health', headers={'host': 'app.researchagentlab.com'}).status_code)\n"
    )
    python_path = os.pathsep.join(
        part for part in (str(config.BASE_DIR), os.environ.get("PYTHONPATH", "")) if part)
    env = {**os.environ, "ALLOWED_HOSTS": "app.researchagentlab.com",
           "DATA_DIR": str(tmp_path / "data"), "EXPERIMENTS_DIR": str(tmp_path / "experiments"),
           "UI_TOKEN": "", "PYTHONPATH": python_path, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          cwd=str(config.BASE_DIR), env=env, timeout=120)
    assert done.returncode == 0, done.stderr[-800:]
    assert done.stdout.split() == ["400", "200"]


def test_a_laptop_answers_to_anything(tmp_path, monkeypatch):
    import ui.app as ui_app

    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UI_TOKEN", "")
    assert config.ALLOWED_HOSTS == []
    client = TestClient(ui_app.app)
    assert client.get("/health", headers={"host": "anything.local"}).status_code == 200


# --- what a fresh machine would be missing --------------------------------------------

def test_everything_the_server_imports_is_declared():
    """
    A package that happens to be installed here but is not in requirements.txt
    is invisible until the first fresh install -- a container, or someone
    cloning the repository -- and then it is a crash mid-run. pandas, scipy,
    pyyaml and the OpenAI SDK were all in exactly that state.
    """
    import ast
    import re
    import sys
    from pathlib import Path

    declared = set()
    for line in (config.BASE_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            declared.add(re.split(r"[<>=\[]", line)[0].strip().lower())

    # Imports that are meant to be absent: the optional local-model and vector
    # backends, and fallbacks tried inside a try/except.
    optional = {"chromadb", "llama_cpp", "PyPDF2", "weasyprint"}
    # Packages that arrive with something already declared.
    comes_with = {"starlette": "fastapi", "pydantic": "fastapi", "fitz": "pymupdf",
                  "yaml": "pyyaml", "dotenv": "python-dotenv"}
    ours = {"config", "router", "agents", "memory", "models", "tools", "ui",
            "analysis_blocks", "panel_data"}

    undeclared: dict[str, str] = {}
    for folder in ("agents", "memory", "models", "tools", "ui"):
        for path in (config.BASE_DIR / folder).rglob("*.py"):
            # The choice-set apparatus is copied into experiment folders and
            # runs there, importing that folder's own modules. It is not part
            # of the server's imports and has its own requirements.txt.
            if path.name.startswith("choice_set"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if name in sys.stdlib_module_names or name in ours or name in optional:
                        continue
                    package = comes_with.get(name, name).lower()
                    if package not in declared:
                        undeclared[name] = str(Path(path).relative_to(config.BASE_DIR))

    assert not undeclared, f"imported but not in requirements.txt: {undeclared}"
