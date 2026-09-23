"""
What the code will actually run against, as opposed to what it asked for.

The runner relaxes the generated requirements to get an install to succeed:
`==` becomes `>=`, upper bounds are dropped, unbuildable packages are removed,
and a batch install that fails is retried package by package with whatever
succeeds counted as success. Every one of those makes an install more likely
and makes the environment less like the one the code was written for.

That gap is invisible in a traceback. `module 'gymnasium' has no attribute
'Tuple'` looks like a typo; part of the reason it appeared at all is that the
code was generated against one version of a library and run against another.

So after installing, this asks the interpreter that will run the experiment two
questions: is everything the code imports actually there, and at which
versions? The answers are written next to the code as `environment.lock.json`,
so a rerun can be compared against the run that produced the results.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)

LOCK_FILE = "environment.lock.json"
_SKIP_DIRS = {"__pycache__", ".git", "results", "data", "outputs", "checkpoints"}

# Import name → the distribution that provides it, where they differ.
_DISTRIBUTION = {
    "sklearn": "scikit-learn", "cv2": "opencv-python", "PIL": "pillow",
    "yaml": "pyyaml", "fitz": "pymupdf", "dotenv": "python-dotenv",
    "datasets": "datasets", "gym": "gym", "gymnasium": "gymnasium",
}


@dataclass
class EnvironmentReport:
    versions: dict[str, str] = field(default_factory=dict)   # import name → version
    missing: list[str] = field(default_factory=list)         # imported, not installed
    python: str = ""

    @property
    def ok(self) -> bool:
        return not self.missing

    def as_dict(self) -> dict:
        return {"python": self.python, "versions": self.versions, "missing": self.missing}


def imported_packages(folder: Path) -> list[str]:
    """
    The third-party packages this experiment imports.

    What a generated `requirements.txt` lists and what the code imports are
    different lists, and only the second one can stop a run. A requirement
    nobody imports is not worth blocking for.
    """
    folder = Path(folder)
    local = {p.stem for p in folder.glob("*.py")} | {p.name for p in folder.iterdir() if p.is_dir()}
    found: set[str] = set()
    for path in folder.rglob("*.py"):
        if _SKIP_DIRS & set(path.relative_to(folder).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for name in names:
                if name and name not in local and name not in sys.stdlib_module_names:
                    found.add(name)
    return sorted(found)


def inspect(folder: Path, python: str | None = None) -> EnvironmentReport:
    """
    Ask the interpreter that will run the experiment what it has.

    It must be that interpreter: `RUNNER_PYTHON` is routinely a different
    environment from the one the server runs in (a GPU conda env, here), and
    the versions that matter are the ones the experiment will see.
    """
    packages = imported_packages(folder)
    if not packages:
        return EnvironmentReport(python="", versions={}, missing=[])

    probe = (
        "import importlib.metadata as m, importlib.util as u, json, sys\n"
        f"names = {packages!r}\n"
        f"dists = {_DISTRIBUTION!r}\n"
        "out = {}\n"
        "for n in names:\n"
        "    if u.find_spec(n) is None:\n"
        "        out[n] = None\n"
        "        continue\n"
        "    try:\n"
        "        out[n] = m.version(dists.get(n, n))\n"
        "    except Exception:\n"
        "        out[n] = 'present'\n"
        "print(json.dumps({'python': sys.version.split()[0], 'packages': out}))\n"
    )
    try:
        done = subprocess.run([python or config.RUNNER_PYTHON or sys.executable, "-c", probe],
                              capture_output=True, text=True, timeout=180)
        data = json.loads(done.stdout.strip().splitlines()[-1])
    except Exception as exc:
        logger.warning("Could not read the experiment's environment: %s", exc)
        return EnvironmentReport(python="", versions={}, missing=[])

    versions = {k: v for k, v in data["packages"].items() if v}
    missing = sorted(k for k, v in data["packages"].items() if not v)
    return EnvironmentReport(versions=versions, missing=missing, python=data["python"])


def write_lock(folder: Path, report: EnvironmentReport) -> Path:
    """
    Record the environment the results were produced in, beside the code.

    Without this, "it worked last month" and "it fails now" cannot be told
    apart from a difference in the code and a difference in a library.
    """
    path = Path(folder) / LOCK_FILE
    path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def summarise(report: EnvironmentReport) -> str:
    """One line for the console and the run record."""
    if not report.versions and not report.missing:
        return "nothing to check"
    kept = ", ".join(f"{k}=={v}" for k, v in sorted(report.versions.items())[:8])
    if report.missing:
        return f"missing: {', '.join(report.missing)} (present: {kept or 'none'})"
    return f"python {report.python}; {kept}"
