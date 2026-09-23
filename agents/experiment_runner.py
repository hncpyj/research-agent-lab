"""
ExperimentRunnerAgent (Phase 6)

Automatically runs the generated experiment code in experiments/hypothesis_N/,
streams output to the console in real time, captures it for the DB, and
auto-fixes runtime errors via the Claude API (max RUNNER_MAX_FIX_ATTEMPTS
per phase).

Pipeline per session:
  install    → pip install -r requirements.txt          (SSL fallback)
  pretrain   → python pretrain.py --config config.yaml  (if pretrain.enabled)
  train      → python train.py --config config.yaml     (checkpoint resume)
  evaluate   → python evaluate.py --config config.yaml  (soft-fail)

Each phase is idempotent: if a 'success' run record already exists for that
session+phase, the phase is skipped (resume support).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from rich.console import Console
from rich.rule import Rule

import config
from router import TaskType

if TYPE_CHECKING:
    from models.api_model import APIModel
    from memory.note_db import NoteDB

logger = logging.getLogger(__name__)
console = Console()

# Model-written code runs unsandboxed on this machine, so it starts from an
# environment with no credentials in it. The Anthropic key was removed here
# already; a 2026-09-20 audit found the rest of .env (OpenAlex key, OpenReview
# password) still reached every experiment subprocess.
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)


def _without_secrets(environ) -> dict:
    return {k: v for k, v in environ.items() if not _SECRET_NAME.search(k)}

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

# The fix prompt once told the model to "implement a numpy-only simulation" and
# "write plausible placeholder results to disk" when a script could not run —
# an instruction to fabricate results that then counted as a fixed, successful
# run. A fix may only repair the error; when it cannot be repaired without
# changing what the script computes, the run must fail.
_FIX_SYSTEM = (
    "You are a senior Python engineer. You are given a Python script that failed at "
    "runtime, the traceback, and the script's current source code. Output ONLY a "
    "corrected, complete version of the file — no explanation, no markdown fences.\n\n"
    "Rules:\n"
    "1. Fix only the error shown. Do not change what the script computes, which data it "
    "reads, its statistical method, or its outputs.\n"
    "2. Never generate synthetic, simulated, random or placeholder data or results, and "
    "never hard-code result values.\n"
    "3. If the error cannot be fixed without breaking rule 1 or 2 (for example a required "
    "package or data file is missing), output the file unchanged.\n"
    "4. The script runs as a subprocess with piped output: use plain print(), no progress "
    "bars or live widgets. Write output to relative paths only."
)

# Bumped whenever the wording below changes, so the repair record can tell a
# change in the prompt apart from a change in the model.
_FIX_PROMPT_VERSION = "2026-09-22.strategies"

_FIX_PROMPT = """\
The following script failed with a non-zero exit code.

=== SCRIPT PATH ===
{script_path}

=== STDERR (last {tail_lines} lines) ===
{stderr_tail}

=== STDOUT (last {tail_lines} lines) ===
{stdout_tail}

=== CONFIG.YAML (use only these keys) ===
{config_content}

=== REPAIR STRATEGY ===
{strategy}

=== RELATED FILES AND ENVIRONMENT ===
{extra_context}

=== CURRENT FILE CONTENT ===
{file_content}

Output ONLY the corrected complete Python source code for {script_name}, or the file
unchanged if it cannot be fixed without changing what it computes.
"""


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences robustly.

    Handles all LLM output variants:
    - ```python\\n...\\n```  or  ```\\n...\\n```
    - ``` python\\n...  (space after backticks)
    - CRLF (\\r\\n) line endings
    - Unclosed fences (opening fence with no closing fence)
    - Trailing/leading prose or blank lines around the code block
    The approach is line-based rather than regex so it cannot be fooled by
    whitespace, language tags, or missing closing fences.
    """
    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = text.split("\n")

    # Case 1: opening fence on first line (most common LLM output)
    if lines and re.match(r"^\s*`{3}", lines[0]):
        lines = lines[1:]
        # Strip closing fence if present
        if lines and re.match(r"^\s*`{3}", lines[-1]):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    # Case 2: prose before/after the code block — extract inner block via regex
    match = re.search(r"```[^\n]*\n(.*?)```", "\n".join(lines), re.DOTALL)
    if match:
        return match.group(1).strip()

    # Case 3: no fence at all — return as-is
    return "\n".join(lines).strip()


def _sanitize_script_file(path: Path) -> None:
    """Strip stray markdown fences from a Python script file in-place.

    Called before every execution attempt so that even if a previous
    auto-fix accidentally wrote fenced content, the script is clean.
    """
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    cleaned = _strip_code_fences(content)
    # Write only if something actually changed (avoid unnecessary disk writes)
    if cleaned != content.rstrip("\n") and cleaned != content.rstrip():
        path.write_text(cleaned + "\n", encoding="utf-8")
        console.print(f"  [dim]Auto-stripped code fences from {path.name}[/]")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class CodeExecutionDisabled(RuntimeError):
    """This server is not allowed to run code a model wrote (config.ALLOW_CODE_EXECUTION)."""


class RepairRefused(RuntimeError):
    """The proposed fix would have changed the experiment rather than repaired it."""


class ExperimentRunnerAgent:
    """
    Phase 6: Runs generated experiment code, monitors it, auto-fixes errors
    via the Claude API, and persists results to the experiment_runs table.
    """

    def __init__(
        self,
        api_model: "APIModel",
        note_db: "NoteDB",
        experiments_base_dir: Path,
        python_executable: str = config.RUNNER_PYTHON,
        install_timeout: int = config.RUNNER_INSTALL_TIMEOUT,
        pretrain_timeout: int | None = None,
        train_timeout: int | None = None,
        evaluate_timeout: int = config.RUNNER_EVALUATE_TIMEOUT,
        max_fix_attempts: int = config.RUNNER_MAX_FIX_ATTEMPTS,
    ) -> None:
        self._api = api_model
        self._ndb = note_db
        self._exp_base = Path(experiments_base_dir)
        self._python = python_executable

        # 0 in config means "no timeout" → map to None for subprocess
        self._timeouts: dict[str, int | None] = {
            "install":  install_timeout or None,
            "pretrain": pretrain_timeout
                        if pretrain_timeout is not None
                        else (config.RUNNER_PRETRAIN_TIMEOUT or None),
            "train":    train_timeout
                        if train_timeout is not None
                        else (config.RUNNER_TRAIN_TIMEOUT or None),
            "evaluate": evaluate_timeout or None,
        }
        self._max_fix = max_fix_attempts

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, session_id: str) -> None:
        """
        Main pipeline for Phase 6.
        Discovers the experiment directory from the session's hypotheses,
        then runs: install → (pretrain) → train → evaluate.
        """
        console.print("\n[bold cyan][Experiment Runner][/] Starting…")

        # Everything below this line runs code that a model wrote. On a server
        # that serves other people, that is remote code execution offered to
        # strangers, and no amount of care in the prompt makes it safe. It
        # stops here rather than part-way through, so nothing half-runs.
        if not config.ALLOW_CODE_EXECUTION:
            raise CodeExecutionDisabled(
                "This server does not run generated code (ALLOW_CODE_EXECUTION=0). "
                "The study is finished up to the code itself; run it on your own "
                "machine, where the code and the data are yours.")

        hypothesis_id, experiment_dir, h_index = self._resolve_experiment(session_id)

        if not experiment_dir.exists():
            raise FileNotFoundError(
                f"Experiment directory not found: {experiment_dir}\n"
                "Run Phase 5 first with:\n"
                f"  python main.py --session {session_id} --experiment"
            )

        console.print(
            f"  Hypothesis: [cyan]{hypothesis_id[:8]}…[/]\n"
            f"  Directory:  [dim]{experiment_dir}[/]"
        )

        # Cheap checks first. A started training job is an expensive way to
        # find a syntax error, and a step the session already recorded as
        # critically wrong must not run at all. What the code imports can only
        # be checked once the environment has been built, so that half of the
        # ladder runs after the install phase.
        from agents import preflight

        report = preflight.check(experiment_dir, db=self._ndb, session_id=session_id,
                                 stages=preflight.BEFORE_INSTALL)
        if not report.passed:
            console.print(f"[bold red]Preflight failed:[/] {report.summary()}")
            raise preflight.PreflightBlocked(report)

        # ---- install ----
        if not self._already_succeeded(session_id, "install"):
            self._run_phase_install(session_id, hypothesis_id, experiment_dir)
        else:
            console.print("[cyan]Skipping install[/] (already succeeded)")

        # Now the environment exists, so the rest of the ladder means something:
        # is everything the code imports actually installed, and does every
        # module import without raising?
        report = preflight.check(experiment_dir, stages=preflight.AFTER_INSTALL)
        if report.environment.get("versions"):
            console.print(f"  [dim]Environment: "
                          f"{', '.join(f'{k}=={v}' for k, v in list(report.environment['versions'].items())[:6])}[/]")
        if not report.passed:
            console.print(f"[bold red]Preflight failed:[/] {report.summary()}")
            self._record_preflight_failure(session_id, report)
            raise preflight.PreflightBlocked(report)

        # An experiment that trains nothing has no pretrain and no train phase:
        # it runs its trials and evaluates them. Asking it for train.py would
        # fail for a reason that has nothing to do with the experiment.
        if (experiment_dir / "run_experiment.py").exists() and not (
                experiment_dir / "train.py").exists():
            self._run_trials(session_id, hypothesis_id, experiment_dir)
            return

        # ---- pretrain (conditional) ----
        if self._read_pretrain_enabled(experiment_dir):
            if not self._already_succeeded(session_id, "pretrain"):
                self._run_phase_script(
                    session_id=session_id,
                    hypothesis_id=hypothesis_id,
                    experiment_dir=experiment_dir,
                    phase="pretrain",
                    script="pretrain.py",
                    extra_args=[],
                    fixable=True,
                )
            else:
                console.print("[cyan]Skipping pretrain[/] (already succeeded)")
        else:
            console.print("[dim]Pretrain disabled in config.yaml — skipping.[/]")

        # ---- train ----
        if not self._already_succeeded(session_id, "train"):
            resume_args = self._detect_resume_args(experiment_dir)
            self._run_phase_script(
                session_id=session_id,
                hypothesis_id=hypothesis_id,
                experiment_dir=experiment_dir,
                phase="train",
                script="train.py",
                extra_args=resume_args,
                fixable=True,
            )
        else:
            console.print("[cyan]Skipping train[/] (already succeeded)")

        # ---- evaluate ----
        if not self._already_succeeded(session_id, "evaluate"):
            self._run_phase_script(
                session_id=session_id,
                hypothesis_id=hypothesis_id,
                experiment_dir=experiment_dir,
                phase="evaluate",
                script="evaluate.py",
                extra_args=[],
                fixable=False,  # evaluation failures are soft errors
            )
        else:
            console.print("[cyan]Skipping evaluate[/] (already succeeded)")

        if not (experiment_dir / "results" / "eval_results.json").exists():
            raise RuntimeError(f"Evaluation finished but {experiment_dir / 'results' / 'eval_results.json'} "
                               "does not exist; the experiment produced no results.")
        console.print(Rule("Experiment Complete", style="green"))

    # ------------------------------------------------------------------
    # Analysis-plan folders (stage S6)
    # ------------------------------------------------------------------

    def run_manifest(self, session_id: str, folder: Path, hypothesis_id: str) -> dict:
        """
        Run an assembled analysis-plan folder (agents/plan_assembly.py) and keep
        a lab notebook. No model is called: the scripts are fixed and tested, so
        an error means the plan or the data does not fit, which a code rewrite
        must not paper over.

        Returns {"status": "passed"|"failed", "problems": [...], "code_hash": ...}.
        """
        # Assembled from fixed scripts, but still executed here: the same rule
        # applies as for generated experiment code.
        if not config.ALLOW_CODE_EXECUTION:
            raise CodeExecutionDisabled(
                "This server does not run analysis code (ALLOW_CODE_EXECUTION=0). "
                "The plan and the assembled scripts are ready; run them on your own "
                "machine, where the data is.")

        import hashlib
        import shutil
        import time
        from datetime import datetime, timezone
        from agents.plan_assembly import verify

        manifest, problems = verify(folder)
        if manifest is None or problems:
            return {"status": "failed", "problems": problems, "code_hash": None}
        code_hash = manifest["code_hash"]
        notebook = folder / "notebook.jsonl"

        def outputs_complete() -> list[str]:
            missing = []
            for rel in manifest["expected_outputs"]:
                path = folder / rel
                if not path.exists():
                    missing.append(f"{rel} was not written")
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("error"):
                    missing.append(f"{record.get('test_id', rel)}: {record['error']}")
            return missing

        previous = []
        if notebook.exists():
            previous = [json.loads(l) for l in notebook.read_text(encoding="utf-8").splitlines() if l.strip()]
        if any(e["code_hash"] == code_hash and e["exit_code"] == 0 for e in previous) and not outputs_complete():
            console.print("[cyan]Analysis already ran with this exact code — results reused.[/]")
            return {"status": "passed", "problems": [], "code_hash": code_hash}
        if not any(e["code_hash"] == code_hash for e in previous) and (folder / "results").exists():
            shutil.rmtree(folder / "results")  # results of different code must not survive

        self._run_phase_install(session_id, hypothesis_id, folder)
        install = self._ndb.get_latest_run(session_id, "install")
        if install is None or install["status"] == "failed":
            return {"status": "failed", "problems": ["installing requirements failed"], "code_hash": code_hash}

        for phase in manifest["phases"]:
            cmd = [self._python, str(folder / phase["script"])]
            run_id = self._ndb.create_experiment_run(session_id, hypothesis_id, phase["phase"])
            started = time.time()
            stdout, stderr, exit_code = self._stream_subprocess(
                cmd=cmd, cwd=folder, timeout=config.RUNNER_ANALYSIS_TIMEOUT or None, phase_label=phase["phase"])
            entry = {
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "phase": phase["phase"], "command": " ".join(cmd[1:]), "code_hash": code_hash,
                "config_hash": manifest["files"]["config.json"], "exit_code": exit_code,
                "seconds": round(time.time() - started, 1),
                "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:],
            }
            with notebook.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._ndb.finish_experiment_run(run_id, "success" if exit_code == 0 else "failed",
                                            stdout=stdout, stderr=stderr)
            if exit_code != 0:
                problems = outputs_complete() or [f"{phase['script']} exited with code {exit_code}"]
                return {"status": "failed", "problems": problems, "code_hash": code_hash}

        problems = outputs_complete()
        return {"status": "failed" if problems else "passed", "problems": problems, "code_hash": code_hash}

    # ------------------------------------------------------------------
    # Phase: resolve experiment directory
    # ------------------------------------------------------------------

    def _resolve_experiment(
        self, session_id: str
    ) -> tuple[str, Path, int]:
        """
        Return (hypothesis_id, experiment_dir, hypothesis_index).

        Strategy:
        1. Find the hypothesis with status 'code_generated'.
        2. Scan experiment_code table to find which hypothesis_N/ folder was
           actually written (ExperimentAgent saves files to the DB with the
           folder index it used — we recover it from file_path prefix).
        3. Fallback: scan self._exp_base for any existing hypothesis_N/ dir
           that contains a config.yaml.
        """
        hypotheses = self._ndb.get_hypotheses(session_id)
        if not hypotheses:
            raise RuntimeError(
                "No hypotheses found for this session. "
                "Run phases 1-5 first."
            )

        # --- Step 1: find the code_generated hypothesis ---
        chosen_hypothesis_id = None
        for h in hypotheses:
            if h.get("status") == "code_generated":
                chosen_hypothesis_id = h["hypothesis_id"]
                break

        if chosen_hypothesis_id is None:
            chosen_hypothesis_id = hypotheses[0]["hypothesis_id"]
            logger.warning(
                "No hypothesis with status 'code_generated'. "
                "Falling back to first hypothesis."
            )

        # The folder is the session's own. It used to be the first
        # experiments/hypothesis_* folder on disk, whichever session wrote it.
        h_index = next((i for i, h in enumerate(hypotheses, start=1)
                        if h["hypothesis_id"] == chosen_hypothesis_id), 1)
        return chosen_hypothesis_id, self._exp_base / session_id, h_index

    # ------------------------------------------------------------------
    # Resume helpers
    # ------------------------------------------------------------------

    def _already_succeeded(self, session_id: str, phase: str) -> bool:
        """True if the most recent run for this session+phase has status 'success'."""
        run = self._ndb.get_latest_run(session_id, phase)
        return run is not None and run["status"] == "success"

    def _read_pretrain_enabled(self, experiment_dir: Path) -> bool:
        """Parse config.yaml and return pretrain.enabled (default False)."""
        config_path = experiment_dir / "config.yaml"
        if not config_path.exists():
            return False
        try:
            with config_path.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            return bool(cfg.get("pretrain", {}).get("enabled", False))
        except Exception as exc:
            logger.warning("Could not parse config.yaml: %s", exc)
            return False

    def _detect_resume_args(self, experiment_dir: Path) -> list[str]:
        """
        Check for existing checkpoints.
        If found, return ['--resume'] so train.py can skip already-done steps.
        """
        config_path = experiment_dir / "config.yaml"
        checkpoint_dir = experiment_dir / "checkpoints"  # default

        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                ckpt_rel = cfg.get("logging", {}).get("checkpoint_dir") or \
                           cfg.get("pretrain", {}).get("pretrained_model_path")
                if ckpt_rel:
                    checkpoint_dir = experiment_dir / ckpt_rel.lstrip("./")
            except Exception:
                pass

        if checkpoint_dir.exists():
            pt_files = list(checkpoint_dir.glob("*.pt"))
            if pt_files:
                names = [f.name for f in pt_files[:3]]
                console.print(
                    f"  [dim]Found checkpoint(s): {names} "
                    "→ passing --resume to train.py[/]"
                )
                return ["--resume"]

        return []

    # ------------------------------------------------------------------
    # Phase: pip install
    # ------------------------------------------------------------------

    # Packages that cannot be installed on Python 3.12+ because they require
    # source compilation with distutils.msvccompiler (removed in Py 3.12) or
    # have no pre-built wheels for Python 3.14.  These are GUI/rendering libs
    # that are never needed when experiments run in numpy simulation mode.
    _UNBUILDABLE = frozenset({
        "pygame",       # no Py3.14 wheel; source build needs distutils.msvccompiler
        "minigrid",     # depends on pygame
        "ale-py",       # Atari ROM loader — source-only, rarely needed
        "gym",          # legacy OpenAI Gym — replaced by gymnasium
    })

    def _sanitize_requirements(self, req_file: Path) -> None:
        """
        Clean requirements.txt so pip can install on Python 3.14:

        1. Remove packages that can never be built on Python 3.14 (no wheel,
           broken source build) — they are GUI libs unused in simulation mode.
        2. Remove upper-bound version constraints:  pkg>=X,<Y  →  pkg>=X
        3. Convert exact pins to lower bounds:      pkg==X.Y   →  pkg>=X.Y
        4. Remove anything that is not a package name (URLs, paths, pip options).
        """
        lines = req_file.read_text(encoding="utf-8").splitlines()
        new_lines, changed = [], False
        for line in lines:
            orig = line.rstrip()
            stripped = orig.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(orig)
                continue

            # 4. A requirement may only name a package on the index. A line that
            #    points pip at a URL, a local path, another index or an editable
            #    checkout is code the model chose to fetch and run, not a
            #    dependency — an audit on 2026-09-20 found nothing stopped it.
            if (stripped.startswith("-")
                    or re.match(r"(?i)^[a-z+]+://", stripped)
                    or stripped.startswith((".", "/", "\\"))
                    or re.match(r"(?i)^[a-z]:[\\/]", stripped)
                    or " @ " in stripped):
                console.print(f"  [yellow]Refused requirement that is not a package name: {stripped!r}[/]")
                changed = True
                continue

            # Extract bare package name (before any version specifier or extras)
            pkg_name = re.split(r"[>=<!;\[\s]", stripped)[0].lower().replace("-", "_")
            if pkg_name in {p.replace("-", "_") for p in self._UNBUILDABLE}:
                console.print(f"  [dim]Removed unbuildable package: {orig.strip()!r}[/]")
                changed = True
                continue  # drop the line entirely

            # Pass 1: strip upper-bound < constraints
            cleaned = re.sub(r",?\s*<\s*[0-9][0-9.]*", "", orig)
            cleaned = re.sub(r"<\s*[0-9][0-9.]*\s*,?\s*", "", cleaned).strip().rstrip(",")
            # Pass 2: convert exact == pins to >= lower bounds
            cleaned = re.sub(r"==([0-9])", r">=\1", cleaned)
            if cleaned != orig:
                console.print(f"  [dim]Relaxed: {orig!r} → {cleaned!r}[/]")
                changed = True
            new_lines.append(cleaned)

        if changed:
            req_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def _run_phase_install(
        self,
        session_id: str,
        hypothesis_id: str,
        experiment_dir: Path,
    ) -> None:
        """
        Run pip install -r requirements.txt.
        On SSL errors, retries with --trusted-host flags.
        Install failures are soft errors (logged, not raised).
        """
        console.print(Rule("Phase: install", style="cyan"))

        req_file = experiment_dir / "requirements.txt"
        if not config.RUNNER_ALLOW_PIP:
            console.print("[yellow]RUNNER_ALLOW_PIP=0 — not installing anything.[/]")
            run_id = self._ndb.create_experiment_run(session_id, hypothesis_id, "install")
            self._ndb.finish_experiment_run(
                run_id, "success",
                stdout="skipped: RUNNER_ALLOW_PIP=0, so the script runs with the packages "
                       "this environment already has",
            )
            return
        if not req_file.exists():
            console.print("[yellow]requirements.txt not found — skipping install.[/]")
            run_id = self._ndb.create_experiment_run(session_id, hypothesis_id, "install")
            self._ndb.finish_experiment_run(
                run_id, "success", stdout="skipped: no requirements.txt"
            )
            return

        run_id = self._ndb.create_experiment_run(session_id, hypothesis_id, "install")

        # Relax upper-bound version pins that may conflict with newer releases
        self._sanitize_requirements(req_file)

        base_cmd = [
            self._python, "-m", "pip", "install", "-r", str(req_file),
            "--retries", "5",          # auto-retry transient SSL/network errors
            "--disable-pip-version-check",
        ]
        # ssl-bypass: keep HTTPS (so binary wheels are found on files.pythonhosted.org)
        # but skip certificate verification with --trusted-host.
        # DO NOT use --index-url http:// — HTTP index cannot discover binary packages.
        ssl_extra = [
            "--trusted-host", "pypi.org",
            "--trusted-host", "files.pythonhosted.org",
        ]
        attempts = [
            ("standard",   base_cmd),
            ("ssl-bypass", base_cmd + ssl_extra),
        ]

        all_stdout = ""
        all_stderr = ""

        for label, cmd in attempts:
            console.print(f"  [dim]pip install ({label})…[/]")
            stdout, stderr, exit_code = self._stream_subprocess(
                cmd=cmd,
                cwd=experiment_dir,
                timeout=self._timeouts["install"],
                phase_label="install",
            )
            all_stdout += stdout
            all_stderr += stderr

            if exit_code == 0:
                self._ndb.finish_experiment_run(
                    run_id, "success",
                    stdout=all_stdout,
                    stderr=all_stderr,
                )
                console.print("[green]Install succeeded.[/]")
                return

            # Detect SSL-related errors
            is_ssl = any(
                kw in (stdout + stderr).lower()
                for kw in ("ssl", "certificate", "handshake", "decryption_failed")
            )
            if label == "standard" and is_ssl:
                console.print(
                    "[yellow]SSL error detected — retrying with "
                    "--trusted-host flags…[/]"
                )
                continue  # try ssl-bypass

            break  # non-SSL failure, don't retry

        # Fallback: --user install (handles WinError 5 / Access Denied when pip
        # tries to uninstall a package owned by another environment, e.g. conda)
        if any(
            kw in (all_stdout + all_stderr).lower()
            for kw in ("winerror 5", "access denied", "permissionerror", "errno 13")
        ):
            console.print(
                "[yellow]Permission error detected — retrying with "
                "--user flag…[/]"
            )
            stdout, stderr, exit_code = self._stream_subprocess(
                cmd=base_cmd + ["--user"],
                cwd=experiment_dir,
                timeout=self._timeouts["install"],
                phase_label="install",
            )
            all_stdout += stdout
            all_stderr += stderr
            if exit_code == 0:
                self._ndb.finish_experiment_run(
                    run_id, "success",
                    stdout=all_stdout,
                    stderr=all_stderr,
                )
                console.print("[green]Install succeeded (--user).[/]")
                return

        # Fallback: install packages one-by-one so that a single build failure
        # (e.g. pygame source build on Python 3.14) doesn't block everything else.
        console.print(
            "[yellow]Batch install failed — retrying packages individually "
            "(build failures will be skipped)…[/]"
        )
        # Use --trusted-host if SSL errors were seen in the batch attempt
        had_ssl = any(
            kw in (all_stdout + all_stderr).lower()
            for kw in ("ssl", "certificate", "handshake", "decryption_failed")
        )
        individual_extra = ["--trusted-host", "pypi.org",
                            "--trusted-host", "files.pythonhosted.org"] if had_ssl else []
        pkg_ok, pkg_fail = [], []
        for pkg_line in req_file.read_text(encoding="utf-8").splitlines():
            pkg_line = pkg_line.strip()
            if not pkg_line or pkg_line.startswith("#"):
                continue
            # --only-binary :all: skips any package with no pre-built wheel
            # (prevents source builds that fail on Python 3.14, e.g. hdbscan)
            _, _, ec = self._stream_subprocess(
                cmd=[self._python, "-m", "pip", "install", pkg_line, "-q",
                     "--only-binary", ":all:",
                     "--retries", "5",
                     "--disable-pip-version-check"] + individual_extra,
                cwd=experiment_dir,
                timeout=300,
                phase_label="install",
            )
            pkg_label = re.split(r"[>=<!;\[\s]", pkg_line)[0].strip()
            (pkg_ok if ec == 0 else pkg_fail).append(pkg_label)

        console.print(
            f"  [dim]Individual install: {len(pkg_ok)} ok, "
            f"{len(pkg_fail)} skipped ({', '.join(pkg_fail[:6])})[/]"
        )
        if pkg_ok:
            # At least some packages installed — treat as partial success
            all_stdout += f"\nIndividual install: {len(pkg_ok)} ok, {len(pkg_fail)} skipped"
            self._ndb.finish_experiment_run(
                run_id, "fixed",
                stdout=all_stdout,
                stderr=all_stderr,
            )
            return

        # Truly nothing installed — soft error
        console.print(
            "[yellow]pip install failed. Continuing — packages may already "
            "be installed in this environment.[/]\n"
            f"[dim]To fix manually: cd {experiment_dir} && "
            "pip install -r requirements.txt[/]"
        )
        self._ndb.finish_experiment_run(
            run_id, "failed",
            stdout=all_stdout,
            stderr=all_stderr,
        )
        # Do NOT raise — install is a soft error

    # ------------------------------------------------------------------
    # Phase: run script with auto-fix loop
    # ------------------------------------------------------------------

    def _run_phase_script(
        self,
        session_id: str,
        hypothesis_id: str,
        experiment_dir: Path,
        phase: str,
        script: str,
        extra_args: list[str],
        fixable: bool,
    ) -> None:
        """
        Run: python <script> --config config.yaml [extra_args]

        If exit code is non-zero and fixable=True:
          - Sends the error context + full file to the Claude API
          - Overwrites the script with the corrected version
          - Retries up to self._max_fix times
        Records result in experiment_runs table.
        """
        console.print(Rule(f"Phase: {phase}", style="cyan"))

        script_path = experiment_dir / script
        if not script_path.exists():
            # Recorded as success until 2026-09-14, so a phase whose script was
            # never generated counted as having run.
            console.print(f"[red]{script} not found — phase {phase} cannot run.[/]")
            run_id = self._ndb.create_experiment_run(session_id, hypothesis_id, phase)
            self._ndb.finish_experiment_run(run_id, "failed", stderr=f"{script} not found")
            raise RuntimeError(f"Phase '{phase}' cannot run: {script} not found in {experiment_dir}")

        cmd = [
            self._python, str(script_path),
            "--config", str(experiment_dir / "config.yaml"),
        ] + extra_args

        fix_attempts = 0
        # What the previous failure was, so the same failure twice can be
        # recognised as "that patch did nothing" rather than spent as a turn.
        last_fingerprint, last_strategy = None, ""
        pending_repair = None
        run_id = self._ndb.create_experiment_run(session_id, hypothesis_id, phase)

        while True:
            # Safety net: strip any stray markdown fences before every execution
            # attempt (in case a previous auto-fix wrote fenced content to disk).
            _sanitize_script_file(script_path)

            attempt_label = (
                f" (fix attempt {fix_attempts}/{self._max_fix})"
                if fix_attempts > 0
                else ""
            )
            console.print(f"  Running [cyan]{script}[/]{attempt_label}…")

            stdout, stderr, exit_code = self._stream_subprocess(
                cmd=cmd,
                cwd=experiment_dir,
                timeout=self._timeouts[phase],
                phase_label=phase,
            )

            if exit_code == 0:
                self._settle_repair(pending_repair, "", succeeded=True)
                pending_repair = None
                metrics = self._parse_metrics(stdout, experiment_dir)
                final_status = "fixed" if fix_attempts > 0 else "success"
                self._ndb.finish_experiment_run(
                    run_id, final_status,
                    stdout=stdout,
                    stderr=stderr,
                    fix_attempts=fix_attempts,
                    metrics=metrics,
                )
                console.print(f"[green]Phase {phase} succeeded.[/]")
                if metrics:
                    console.print(f"  [dim]Metrics: {metrics}[/]")
                return

            # Process exited with error
            console.print(f"[red]{script} exited with code {exit_code}.[/]")

            # Whatever the last patch was meant to do, this is what it did.
            self._settle_repair(pending_repair, stderr, succeeded=False,
                                experiment_dir=experiment_dir)
            pending_repair = None

            if not fixable:
                # Was a soft error: the pipeline went on to review and report
                # an experiment whose evaluation never produced results.
                self._ndb.finish_experiment_run(
                    run_id, "failed",
                    stdout=stdout,
                    stderr=stderr,
                    fix_attempts=fix_attempts,
                )
                raise RuntimeError(
                    f"Phase '{phase}' failed (exit code {exit_code}).\nLast stderr (tail):\n{stderr[-2000:]}"
                )

            if fix_attempts >= self._max_fix:
                self._ndb.finish_experiment_run(
                    run_id, "failed",
                    stdout=stdout,
                    stderr=stderr,
                    fix_attempts=fix_attempts,
                )
                raise RuntimeError(
                    f"Phase '{phase}' failed after {fix_attempts} fix attempt(s).\n"
                    f"Last stderr (tail):\n{stderr[-2000:]}"
                )

            # Attempt auto-fix via API
            fix_attempts += 1
            plan = self._plan_repair(
                experiment_dir=experiment_dir,
                entry_script=script_path,
                stderr=stderr,
                previous=last_fingerprint,
                previous_strategy=last_strategy,
            )
            last_fingerprint, last_strategy = plan["fingerprint"], plan["strategy"]
            pending_repair = self._record_repair(session_id, phase, fix_attempts, plan,
                                                 experiment_dir)
            console.print(
                f"  [yellow]Auto-fixing {plan['target'].name} — {plan['strategy']} "
                f"(attempt {fix_attempts}/{self._max_fix})…[/]"
            )
            try:
                self._apply_api_fix(
                    script_path=plan["target"],
                    stdout_tail=stdout[-3000:],
                    stderr_tail=stderr[-3000:],
                    context=plan["context"],
                    strategy=plan["strategy"],
                )
            except Exception as exc:
                logger.error("Auto-fix API call failed: %s", exc)
                from memory import repair_log
                if pending_repair:
                    repair_log.settle(pending_repair[0],
                                      repair_log.REFUSED if isinstance(exc, RepairRefused)
                                      else "failed_to_apply",
                                      refusal_reason=str(exc)[:500])
                    pending_repair = None
                self._ndb.finish_experiment_run(
                    run_id, "failed",
                    stdout=stdout,
                    stderr=stderr,
                    fix_attempts=fix_attempts,
                )
                if isinstance(exc, RepairRefused):
                    raise RuntimeError(
                        f"Phase '{phase}' failed and the proposed fix was refused: {exc}"
                    ) from exc
                raise RuntimeError(
                    f"Phase '{phase}' failed and API auto-fix also failed: {exc}"
                ) from exc
            # Loop to retry with the patched script

    def _run_trials(self, session_id: str, hypothesis_id: str, experiment_dir: Path) -> None:
        """
        The run phases of an experiment that trains nothing: the trials, then
        the summary computed from what they wrote.
        """
        for phase, script, fixable in (("run_experiment", "run_experiment.py", True),
                                       ("evaluate", "evaluate.py", False)):
            if not (experiment_dir / script).exists():
                continue
            if self._already_succeeded(session_id, phase):
                console.print(f"[cyan]Skipping {phase}[/] (already succeeded)")
                continue
            self._run_phase_script(
                session_id=session_id, hypothesis_id=hypothesis_id,
                experiment_dir=experiment_dir, phase=phase, script=script,
                extra_args=[], fixable=fixable)

    # ------------------------------------------------------------------
    # Keeping the repair record
    # ------------------------------------------------------------------

    def _record_preflight_failure(self, session_id: str, report) -> None:
        """A run stopped before it started still has to say so in the session."""
        try:
            from agents.degradation import DegradationLog

            DegradationLog(self._ndb, session_id).record(
                6, "preflight", "critical", report.summary())
        except Exception as exc:
            logger.warning("Could not record the preflight failure: %s", exc)

    def _record_repair(self, session_id: str, phase: str, attempt: int,
                       plan: dict, experiment_dir: Path):
        """Write down what is about to be tried, to be settled after the rerun."""
        from memory import repair_log

        try:
            target = str(Path(plan["target"]).relative_to(experiment_dir)).replace("\\", "/")
        except ValueError:
            target = Path(plan["target"]).name
        try:
            row = repair_log.record(
                session_id=session_id, phase=phase, attempt=attempt,
                strategy=plan["strategy"], target_file=target,
                culprit_file=plan["fingerprint"].culprit_file,
                fingerprint_before=str(plan["fingerprint"]),
                model_id=self._model_id(),
                prompt_version=_FIX_PROMPT_VERSION)
        except Exception as exc:                  # bookkeeping must not stop a run
            logger.warning("Could not record the repair attempt: %s", exc)
            return None
        return (row, plan["fingerprint"])

    def _model_id(self) -> str:
        """Which model made the patch, when the backend will say."""
        name = getattr(self._api, "_model", "")
        return name if isinstance(name, str) else ""

    def _settle_repair(self, pending, stderr: str, succeeded: bool,
                       experiment_dir: Path | None = None) -> None:
        """Say what the attempt achieved: fixed, progressed, or nothing at all."""
        if not pending:
            return
        from agents import error_diagnostics as diag
        from memory import repair_log

        row, before = pending
        after = ""
        if not succeeded and experiment_dir is not None:
            after = str(diag.fingerprint(stderr, experiment_dir))
        outcome = repair_log.judge(str(before), after, succeeded)
        if outcome == repair_log.SAME_ERROR:
            console.print("  [dim]That patch left the same failure behind.[/]")
        try:
            repair_log.settle(row, outcome, after)
        except Exception as exc:
            logger.warning("Could not settle the repair attempt: %s", exc)

    # ------------------------------------------------------------------
    # Planning a repair
    # ------------------------------------------------------------------

    # What each attempt is for. Three attempts that ask the same question three
    # times are one attempt with two repetitions; these are three questions.
    LOCAL_PATCH = "local patch"              # the file the traceback names
    ROOT_CAUSE = "root cause"                # that file, what it imports, and versions
    REGENERATE = "regenerate"                # write the component again

    _ESCALATION = [LOCAL_PATCH, ROOT_CAUSE, REGENERATE]

    def _plan_repair(self, experiment_dir: Path, entry_script: Path, stderr: str,
                     previous=None, previous_strategy: str = "") -> dict:
        """
        Decide what to fix and how, from the traceback rather than from which
        script happened to be launched.

        The strategy follows what the last attempt achieved, not how many have
        been spent. The same fingerprint again means the patch did not reach
        the cause, so the next attempt asks a wider question; a *different*
        failure means the last cause was fixed and this new one deserves the
        same cheap, targeted attempt the first one got.
        """
        from agents import error_diagnostics as diag

        fingerprint = diag.fingerprint(stderr, experiment_dir)
        culprit = diag.culprit(stderr, experiment_dir)
        target = Path(culprit.file) if culprit else entry_script
        if not target.exists():
            target = entry_script

        repeated = previous is not None and fingerprint == previous
        if repeated:
            console.print("  [dim]Same failure as last time — the previous patch did not "
                          "reach the cause; asking a wider question.[/]")
            level = self._ESCALATION.index(previous_strategy) if previous_strategy in self._ESCALATION else 0
            strategy = self._ESCALATION[min(level + 1, len(self._ESCALATION) - 1)]
        else:
            strategy = self.LOCAL_PATCH

        return {"target": target, "strategy": strategy, "fingerprint": fingerprint,
                "context": self._repair_context(experiment_dir, entry_script, target, strategy)}

    def _repair_context(self, experiment_dir: Path, entry_script: Path,
                        target: Path, strategy: str) -> str:
        """
        What the model is shown besides the failing file. A local patch needs
        nothing more; a root-cause attempt needs the files this one imports and
        the versions actually installed, because that is where this class of
        mistake usually lives.
        """
        if strategy == self.LOCAL_PATCH:
            return ""

        from agents import error_diagnostics as diag

        parts: list[str] = []
        try:
            source = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = ""
        for name in diag.local_imports(source, experiment_dir)[:4]:
            path = experiment_dir / name
            if path.exists() and path != target:
                body = path.read_text(encoding="utf-8", errors="replace")[:4000]
                parts.append(f"=== {name} (imported by the failing file) ===\n{body}")

        if target != entry_script and entry_script.exists():
            head = entry_script.read_text(encoding="utf-8", errors="replace")[:2000]
            parts.append(f"=== {entry_script.name} (the script that was run) ===\n{head}")

        versions = self._installed_versions(source)
        if versions:
            parts.append("=== INSTALLED VERSIONS ===\n" + versions)

        if strategy == self.REGENERATE:
            parts.append("=== NOTE ===\nTwo patches have already failed to fix this. "
                         "Rewrite this file so it does its stated job correctly, keeping "
                         "the same imports, function names and outputs that the rest of "
                         "the project expects.")
        return "\n\n".join(parts)

    def _installed_versions(self, source: str) -> str:
        """
        The versions actually present, for the packages this file imports.

        The runner relaxes pinned requirements to get an install to succeed, so
        the version the generated code was written against and the one it runs
        against are routinely different. That difference is invisible in a
        traceback and is exactly what produced `gymnasium.Tuple`.
        """
        import importlib.metadata as metadata
        import re as _re

        names = sorted(set(_re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_][\w]*)", source, _re.M)))
        lines = []
        for name in names[:12]:
            try:
                lines.append(f"{name}=={metadata.version(name)}")
            except Exception:
                continue
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Auto-fix via API
    # ------------------------------------------------------------------

    def _apply_api_fix(
        self,
        script_path: Path,
        stdout_tail: str,
        stderr_tail: str,
        context: str = "",
        strategy: str = "local patch",
    ) -> None:
        """
        Send the failing file and what is known about the failure to the API,
        and write back the corrected version.

        `script_path` is the file the traceback blames, which is not always the
        script that was launched: a wrapper three imports deep is a far more
        common culprit than the entry point, and rewriting the entry point
        leaves such a fault exactly where it was.
        """
        # Strip any fences from current file before sending to API —
        # if a previous fix wrote fenced code, sending it as-is confuses the LLM
        # into producing more fenced output.
        file_content = _strip_code_fences(script_path.read_text(encoding="utf-8"))
        script_name  = script_path.name
        tail_lines   = 50

        # Include config.yaml so the LLM uses correct key names
        config_yaml_path = script_path.parent / "config.yaml"
        config_content = (
            config_yaml_path.read_text(encoding="utf-8")
            if config_yaml_path.exists()
            else "(config.yaml not found)"
        )

        prompt = _FIX_PROMPT.format(
            strategy=strategy,
            extra_context=context or "(none)",
            script_path=str(script_path),
            tail_lines=tail_lines,
            stderr_tail="\n".join(stderr_tail.splitlines()[-tail_lines:]),
            stdout_tail="\n".join(stdout_tail.splitlines()[-tail_lines:]),
            config_content=config_content,
            file_content=file_content,
            script_name=script_name,
        )

        fixed_code = self._api.generate(
            prompt=prompt,
            system=_FIX_SYSTEM,
            task_type=TaskType.ERROR_FIXING,
            max_tokens=8192,
            temperature=0.1,
        )

        fixed_code = _strip_code_fences(fixed_code)

        # A repair may fix the error. It may not change the experiment: a patch
        # that invents data, reads something else, or stops writing results has
        # turned a failed run into a fabricated one, which is worse.
        from tools.patch_guard import check as _guard

        from agents.experiment_spec import ExperimentSpec

        spec = ExperimentSpec.read(script_path.parent) or ExperimentSpec.read(
            script_path.parent.parent)
        verdict = _guard(file_content, fixed_code, filename=script_name, spec=spec)
        if not verdict.allowed:
            console.print(f"  [bold red]Refused the patch to {script_name}:[/] {verdict.why()}")
            raise RepairRefused(f"the proposed fix to {script_name} would change the "
                                f"experiment: {verdict.why()}")

        script_path.write_text(fixed_code, encoding="utf-8")
        console.print(
            f"  [dim]Overwrote {script_name} with API-fixed version "
            f"({len(fixed_code):,} chars)[/]"
        )

    # ------------------------------------------------------------------
    # Subprocess streaming (stdout + stderr in real time)
    # ------------------------------------------------------------------

    def _stream_subprocess(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: int | None,
        phase_label: str,
    ) -> tuple[str, str, int]:
        """
        Launch cmd in cwd. Stream stdout/stderr to console in real time
        while also capturing them for DB storage.

        Uses two background threads to drain stdout and stderr concurrently,
        avoiding OS pipe buffer deadlocks that can occur with large output.

        Returns (captured_stdout, captured_stderr, exit_code).
        exit_code = -1 on timeout or KeyboardInterrupt.
        """
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        env = _without_secrets(os.environ)
        # Add experiment dir to PYTHONPATH so intra-package imports work
        env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")
        # Force UTF-8 for the subprocess's own stdout/stderr, and disable
        # Rich's animated/colored output (prevents LegacyWindowsTerm cp949 crashes)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["NO_COLOR"] = "1"          # Rich: plain text, no ANSI/Windows Console API
        env["FORCE_COLOR"] = "0"       # Belt-and-suspenders for other colour libs

        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,  # line-buffered
        )

        def _drain(pipe, line_buf: list[str], prefix: str) -> None:
            try:
                for line in pipe:
                    stripped = line.rstrip("\n")
                    line_buf.append(stripped)
                    console.print(f"  [dim][{prefix}][/] {stripped}")
            except ValueError:
                pass  # pipe closed unexpectedly

        t_out = threading.Thread(
            target=_drain,
            args=(process.stdout, stdout_lines, phase_label),
            daemon=True,
        )
        t_err = threading.Thread(
            target=_drain,
            args=(process.stderr, stderr_lines, "ERR"),
            daemon=True,
        )
        t_out.start()
        t_err.start()

        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            t_out.join(timeout=5)
            t_err.join(timeout=5)
            console.print(
                f"[red]Phase '{phase_label}' timed out after {timeout}s. "
                "Process killed.[/]"
            )
            return (
                "\n".join(stdout_lines),
                "\n".join(stderr_lines) + f"\n[TIMEOUT after {timeout}s]",
                -1,
            )
        except KeyboardInterrupt:
            process.kill()
            t_out.join(timeout=5)
            t_err.join(timeout=5)
            raise
        finally:
            t_out.join()
            t_err.join()

        return (
            "\n".join(stdout_lines),
            "\n".join(stderr_lines),
            exit_code,
        )

    # ------------------------------------------------------------------
    # Metrics parsing
    # ------------------------------------------------------------------

    def _parse_metrics(
        self,
        stdout: str,
        experiment_dir: Path,
    ) -> dict | None:
        """
        Try to extract numeric metrics from:
        1. results/eval_results.json (written by evaluate.py)
        2. JSON blobs in stdout containing known metric keys
        Returns a dict or None.
        """
        # Priority 1: look for eval_results.json
        results_path = experiment_dir / "results" / "eval_results.json"
        if results_path.exists():
            try:
                with results_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # Priority 2: scan stdout for JSON with known metric keys
        metric_patterns = [
            r'\{[^{}]*"credit_assignment_gap"[^{}]*\}',
            r'\{[^{}]*"mean_return"[^{}]*\}',
            r'\{[^{}]*"eval_return"[^{}]*\}',
        ]
        for pattern in metric_patterns:
            match = re.search(pattern, stdout, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass

        return None
