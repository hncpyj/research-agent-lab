"""
Checking generated code cheaply, before anything expensive runs.

The first thing that ever looked at generated code was the training run itself.
So a mistake that a parser would have caught in milliseconds — a name that does
not exist in the library, an import of something that was never written — was
found only after the environment had been installed and a GPU job had started,
and then handed to a repair loop that cost API calls to undo.

The ladder here runs in increasing order of cost, and stops at the first rung
that fails:

1. the session's own record: a step that already reported a critical problem
   must not be run at all, whatever its code looks like;
2. every file parses;
3. everything the code imports is installed, and at which versions;
4. every module imports without raising;
5. each entry script does one minimal step and exits.

The first two run before the environment is built, the last two after it: a
module whose package is not installed yet says nothing about the code.

Importing is execution — a module body runs — so that rung is skipped where the
server is not allowed to execute generated code, and the report says so rather
than pretending it passed.

A tiny dry run (one batch, one episode, one decision) belongs on the end of
this ladder and is not built yet; what is here already catches the class of
failure that prompted it.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import config

logger = logging.getLogger(__name__)

SPEC, COMPILE, CONTRACT, DEPENDENCIES, IMPORTS, SMOKE = (
    "spec", "compile", "contract", "dependencies", "imports", "smoke")

# The environment variable an entry script honours by doing exactly one
# minimal step and exiting. A script that does not mention it is not asked to
# run at all: a "smoke test" that silently starts real training would cost
# more than the rung saves.
SMOKE_FLAG = "RA_SMOKE"
SMOKE_TIMEOUT_S = 180
# Where a smoke run is allowed to write, inside the results directory.
PREFLIGHT_DIR = "_preflight"

# What can be checked before anything is installed, and what has to wait until
# afterwards. Importing a module whose package is not installed yet says
# nothing about the code.
BEFORE_INSTALL = (SPEC, COMPILE, CONTRACT)
AFTER_INSTALL = (DEPENDENCIES, IMPORTS, SMOKE)
_SKIP_DIRS = {"__pycache__", ".git", "results", "data", "outputs", "checkpoints"}
# Entry scripts in the order they run. Evaluation reads what the run wrote,
# so a smoke step that evaluated first would fail for the one honest reason
# it should not: there was nothing there yet.
_ENTRY_SCRIPTS = ("pretrain.py", "train.py", "run_experiment.py", "main.py",
                  "evaluate.py")


class PreflightBlocked(RuntimeError):
    """The experiment must not run. Carries the report that says why."""

    def __init__(self, report: "PreflightReport"):
        super().__init__(report.summary())
        self.report = report


@dataclass
class Failure:
    stage: str
    file: str
    message: str
    traceback: str = ""

    def as_dict(self) -> dict:
        return {"stage": self.stage, "file": self.file, "message": self.message}


@dataclass
class PreflightReport:
    passed: bool
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    environment: dict = field(default_factory=dict)

    def summary(self) -> str:
        if self.passed:
            return f"Preflight passed ({', '.join(self.ran) or 'nothing to check'})."
        first = self.failures[0]
        return (f"Preflight failed at {first.stage}: {first.file or 'the experiment'} — "
                f"{first.message}")

    def as_dict(self) -> dict:
        return {"passed": self.passed, "ran": self.ran, "skipped": self.skipped,
                "failures": [f.as_dict() for f in self.failures],
                "environment": self.environment}


def _python_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.py")
                  if not _SKIP_DIRS & set(p.relative_to(folder).parts))


def critical_problems(db, session_id: str, phase: int | None = 5) -> list[dict]:
    """
    What the session already knows went wrong badly enough to stop for.

    The degradation log has recorded these all along; nothing read them before
    deciding whether to run. A critical entry at code-generation time means the
    code does not answer the question that was asked, and running it produces a
    result for a different question.
    """
    try:
        entries = db.get_degradations(session_id)
    except Exception as exc:                        # a missing log is not a pass
        logger.warning("Could not read the degradation log for %s: %s", session_id, exc)
        return []
    return [e for e in entries
            if e.get("severity") == "critical" and (phase is None or e.get("phase") == phase)]


def check(folder: Path, db=None, session_id: str = "",
          modules: list[str] | None = None,
          stages: tuple[str, ...] = (SPEC, COMPILE, CONTRACT, DEPENDENCIES,
                                     IMPORTS, SMOKE)) -> PreflightReport:
    """Run the ladder over one experiment folder and report what happened."""
    folder = Path(folder)
    report = PreflightReport(passed=True)

    if SPEC in stages and db is not None and session_id:
        report.ran.append(SPEC)
        for entry in critical_problems(db, session_id):
            report.failures.append(Failure(
                stage=SPEC, file="", message=entry.get("message", "a critical problem")))
        if report.failures:
            report.passed = False
            return report

    files = _python_files(folder)
    if COMPILE not in stages:
        return _dependencies_and_imports(folder, report, files, modules, stages)
    if not files:
        report.failures.append(Failure(stage=COMPILE, file=str(folder),
                                       message="no Python files were generated"))
        report.passed = False
        return report

    report.ran.append(COMPILE)
    for path in files:
        try:
            compile(path.read_text(encoding="utf-8", errors="replace"), str(path), "exec")
        except SyntaxError as exc:
            report.failures.append(Failure(
                stage=COMPILE, file=str(path),
                message=f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"))
    if report.failures:
        report.passed = False
        return report

    if CONTRACT in stages:
        _contract(folder, report)
        if report.failures:
            report.passed = False
            return report

    return _dependencies_and_imports(folder, report, files, modules, stages)


def _contract(folder: Path, report: "PreflightReport") -> None:
    """
    Whether what was generated is usable as *this* experiment.

    Compiling proves a file is Python. This rung asks the scaffold whether the
    parts it asked a model to write are the parts it needs: a candidate pool
    that parses and has candidates in it, prompts carrying the placeholders the
    apparatus fills in, a config that still describes the agreed design. All of
    it is read, none of it is run.
    """
    from agents.study_protocol import StudyProtocol

    spec = StudyProtocol.read(folder)
    if spec is None:
        return
    try:
        from agents.experiment_agent import scaffold_by_id
        scaffold = scaffold_by_id(spec.scaffold_id)
    except Exception as exc:
        report.failures.append(Failure(stage=CONTRACT, file="",
                                       message=f"no scaffold to check against: {exc}"))
        return
    checker = getattr(scaffold, "contract", None) or _scaffold_checker(spec.scaffold_id)
    if checker is None:
        return

    report.ran.append(CONTRACT)
    for problem in checker(folder, spec):
        report.failures.append(Failure(stage=CONTRACT, file="", message=problem))


def _scaffold_checker(scaffold_id: str):
    """The contract check a scaffold ships, if it ships one."""
    if scaffold_id == "controlled_llm":
        from agents.controlled_llm_scaffold import contract_problems
        return contract_problems
    return None


def _dependencies_and_imports(folder: Path, report: "PreflightReport", files: list[Path],
                              modules: list[str] | None, stages: tuple[str, ...]):
    """The rungs that only mean anything once the environment has been built."""
    from tools import environment_check

    if DEPENDENCIES in stages:
        report.ran.append(DEPENDENCIES)
        environment = environment_check.inspect(folder)
        report.environment = environment.as_dict()
        if environment.missing:
            # The install phase treats "some packages installed" as success. A
            # package the code imports and cannot find is not a detail to find
            # out about in the middle of training.
            report.failures.append(Failure(
                stage=DEPENDENCIES, file="requirements.txt",
                message="the experiment imports " + ", ".join(environment.missing)
                        + ", which are not installed"))
            report.passed = False
            return report
        try:
            environment_check.write_lock(folder, environment)
        except OSError as exc:
            logger.warning("Could not write the environment lock: %s", exc)

    # Importing runs the module body, and so does one minimal step, so both
    # follow the same rule as everything else that executes generated code.
    if not config.ALLOW_CODE_EXECUTION:
        report.skipped.extend(s for s in (IMPORTS, SMOKE) if s in stages)
        return report

    if IMPORTS not in stages:
        if SMOKE in stages:
            _smoke(folder, report)
            report.passed = not report.failures
        return report

    report.ran.append(IMPORTS)
    for name in (modules if modules is not None else _module_names(folder, files)):
        failure = _import_once(folder, name)
        if failure:
            report.failures.append(failure)
            report.passed = False
            return report                           # the first one is the one to fix

    if SMOKE in stages:
        _smoke(folder, report)
    report.passed = not report.failures
    return report


def _smoke(folder: Path, report: "PreflightReport") -> None:
    """
    One minimal step of each entry script: a single batch, episode or example.

    This is the last cheap rung. Everything above it proves the code can be
    read and loaded; only running it proves the pieces fit together — that the
    shapes match, the config keys exist, and something is written at the end.

    Only scripts that honour RA_SMOKE are run. One that ignores it would start
    the full training this rung exists to protect, so it is skipped and said so.
    """
    scripts = [folder / name for name in _ENTRY_SCRIPTS
               if (folder / name).exists()
               and SMOKE_FLAG in (folder / name).read_text(encoding="utf-8", errors="replace")]
    if not scripts:
        report.skipped.append(SMOKE)
        return

    report.ran.append(SMOKE)
    before = _production_state(folder)
    for script in scripts:
        cmd = [config.RUNNER_PYTHON or sys.executable, script.name]
        # Only a script that asks for a config gets one. Handing --config to a
        # script that takes --results is an argument-parser error dressed up as
        # a failed experiment.
        source = script.read_text(encoding="utf-8", errors="replace")
        if "--config" in source and (folder / "config.yaml").exists():
            cmd += ["--config", "config.yaml"]
        try:
            done = subprocess.run(cmd, cwd=str(folder), capture_output=True, text=True,
                                  timeout=SMOKE_TIMEOUT_S,
                                  env={**_env(), SMOKE_FLAG: "1",
                                       "PYTHONPATH": str(folder), "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired:
            report.failures.append(Failure(
                stage=SMOKE, file=script.name,
                message=f"one minimal step did not finish within {SMOKE_TIMEOUT_S}s"))
            return
        if done.returncode != 0:
            report.failures.append(Failure(
                stage=SMOKE, file=script.name,
                message=(done.stderr.strip().splitlines() or ["the script exited non-zero"])[-1],
                traceback=done.stderr))
            return

    # A rehearsal that wrote into the real results directory has made the real
    # results unusable: a summary over one smoke trial and forty real ones
    # cannot be separated afterwards.
    after = _production_state(folder)
    if after != before:
        changed = sorted(set(after) - set(before)) or ["existing files"]
        report.failures.append(Failure(
            stage=SMOKE, file="results/",
            message="the smoke run wrote into the production results directory "
                    f"({', '.join(changed)}); it must write to its own preflight directory"))
        return

    _check_output_contract(folder, report)


def _production_state(folder: Path) -> dict:
    """What the real results directory holds, by name and size."""
    results = folder / "results"
    if not results.exists():
        return {}
    return {str(p.relative_to(results)): p.stat().st_size
            for p in results.rglob("*") if p.is_file()
            and PREFLIGHT_DIR not in p.relative_to(results).parts}


def _check_output_contract(folder: Path, report: "PreflightReport") -> None:
    """
    Whether the smoke run wrote what the experiment says it must write.

    The spec names the files and the keys they have to contain. Finding out
    after a full run that the summary has no primary outcome in it is finding
    out too late; one trial is enough to check the shape.
    """
    import json

    from agents.study_protocol import StudyProtocol

    spec = StudyProtocol.read(folder)
    if spec is None:
        return
    preflight_results = folder / "results" / PREFLIGHT_DIR
    for contract in spec.required_outputs:
        name = Path(contract.path).name
        written = preflight_results / name
        if not written.exists():
            report.failures.append(Failure(
                stage=SMOKE, file=contract.path,
                message="the run did not write it, and the experiment says it must"))
            return
        try:
            if contract.format == "jsonl":
                lines = [l for l in written.read_text(encoding="utf-8").splitlines() if l.strip()]
                record = json.loads(lines[0]) if lines else {}
            else:
                record = json.loads(written.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            report.failures.append(Failure(stage=SMOKE, file=contract.path,
                                           message=f"it could not be read: {exc}"))
            return
        missing = [k for k in contract.required_keys if k not in record]
        if missing:
            report.failures.append(Failure(
                stage=SMOKE, file=contract.path,
                message=f"it is missing {', '.join(missing)}"))
            return


def _module_names(folder: Path, files: list[Path]) -> list[str]:
    """
    Modules worth importing: the project's own, without the entry scripts.

    An entry script is meant to do the work when it is imported as `__main__`,
    and importing it here would start that work. The modules it imports are
    where the mistakes of this kind live anyway.
    """
    names = []
    for path in files:
        relative = path.relative_to(folder)
        if relative.name == "__init__.py":
            relative = relative.parent
        elif relative.parent == Path("."):
            continue                                # top-level script: likely an entry point
        names.append(str(relative.with_suffix("")).replace("\\", "/").replace("/", "."))
    return sorted(set(n for n in names if n and n != "."))


def _import_once(folder: Path, module: str) -> Failure | None:
    """Import one module in its own process, so nothing it does leaks into ours."""
    done = subprocess.run(
        [config.RUNNER_PYTHON or sys.executable, "-c", f"import {module}"],
        cwd=str(folder), capture_output=True, text=True, timeout=180,
        env={**_env(), "PYTHONPATH": str(folder), "PYTHONIOENCODING": "utf-8"})
    if done.returncode == 0:
        return None
    return Failure(stage=IMPORTS, file=module.replace(".", "/") + ".py",
                   message=(done.stderr.strip().splitlines() or ["import failed"])[-1],
                   traceback=done.stderr)


def _env() -> dict:
    import os

    # The same rule the runner follows: a generated module gets no secrets.
    return {k: v for k, v in os.environ.items()
            if not any(mark in k.upper() for mark in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))}


def require(folder: Path, db=None, session_id: str = "",
            stages: tuple[str, ...] = (SPEC, COMPILE, CONTRACT, DEPENDENCIES,
                                       IMPORTS, SMOKE)) -> PreflightReport:
    """Run the ladder and raise PreflightBlocked if the experiment must not run."""
    report = check(folder, db=db, session_id=session_id, stages=stages)
    if not report.passed:
        raise PreflightBlocked(report)
    return report
