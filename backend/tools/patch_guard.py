"""
Checking that a repair fixed the error and not the experiment.

The repair prompt already says it: fix the error, do not change what the script
computes, never invent data. A prompt is a request. This is the check.

The failure it exists for is specific and has happened: a script cannot reach
its data, so the "fix" replaces the loader with `np.random.randn(...)`, the run
then succeeds, and a report is written about numbers that came from nowhere. A
run that fails loudly costs an afternoon; a run that succeeds on invented data
costs whatever is built on top of it afterwards.

Each check compares the file before the patch with the file after, so it
catches what the patch *introduced* rather than what the generator wrote. A
tripped check rejects the patch and keeps the original file: the error stays,
which is the honest outcome.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Calls that make up numbers. Their appearance in a *repair* is the signature
# of "I could not get the real data, so here is some data".
_FABRICATION = re.compile(
    r"\b(np|numpy)\.random\.|"
    r"\brandom\.(random|randint|uniform|gauss|choice|sample)\b|"
    r"\btorch\.(randn|rand|randint)\b|"
    r"\bmake_classification\b|\bmake_regression\b|\bmake_blobs\b")

# Words a model reaches for when it is standing in for the real thing.
_PLACEHOLDER = re.compile(
    r"(?i)\b(placeholder|dummy data|synthetic data|simulated (?:data|results)|"
    r"mock(?:ed)? (?:data|results)|fake (?:data|results)|for demonstration)\b")

# Where the data comes from: changing any of these changes the experiment.
_DATA_SOURCE = re.compile(
    r"(?:load_dataset|read_csv|read_parquet|read_json|gym\.make|gymnasium\.make|"
    r"from_pretrained|ImageFolder|load_from_disk)\s*\(\s*[rfbu]*['\"]([^'\"]+)['\"]")

# Somewhere results are written. A patch that stops writing them turns a
# failure into a silent one.
_OUTPUT = re.compile(r"(?:open|to_csv|to_json|savefig|save|write_text|dump)\s*\(\s*"
                     r"[rfbu]*['\"]([^'\"]+)['\"]")

_SHRANK_TO = 0.4           # a patch that keeps under this much of the file


@dataclass
class GuardResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def why(self) -> str:
        return "; ".join(self.reasons)


def _literals(pattern: re.Pattern, source: str) -> set[str]:
    """The quoted paths a pattern names. The quotes and any string prefix are
    outside the capture, so a path beginning with r, f, b or u keeps its first
    letter -- stripping those characters turned results/ into esults/."""
    return {m.group(1) for m in pattern.finditer(source)}


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


def check(before: str, after: str, *, filename: str = "", spec=None) -> GuardResult:
    """
    Whether this patch may be written to disk.

    `before` and `after` are the file's contents either side of the repair.
    `spec` is the ExperimentSpec the study was generated from, when there is
    one: with it, the checks extend from "is this still the same program" to
    "is this still the same experiment".
    """
    reasons: list[str] = []

    if not after.strip():
        return GuardResult(False, ["the patch is empty"])

    if not _parses(after):
        reasons.append("the patched file does not parse")

    # 1. Numbers that came from nowhere.
    if _FABRICATION.search(after) and not _FABRICATION.search(before):
        reasons.append("the patch adds generated random data where the file had none")
    if _PLACEHOLDER.search(after) and not _PLACEHOLDER.search(before):
        reasons.append("the patch describes its own output as placeholder or simulated")

    # 2. A different source of data is a different experiment.
    sources_before, sources_after = _literals(_DATA_SOURCE, before), _literals(_DATA_SOURCE, after)
    dropped = sources_before - sources_after
    if dropped:
        reasons.append(f"the patch stops reading {', '.join(sorted(dropped))}")
    added = sources_after - sources_before
    if added and sources_before:
        reasons.append(f"the patch reads {', '.join(sorted(added))} instead")

    # 3. Results that are no longer written.
    lost_outputs = _literals(_OUTPUT, before) - _literals(_OUTPUT, after)
    if lost_outputs:
        reasons.append(f"the patch no longer writes {', '.join(sorted(lost_outputs))}")

    # 4. A file that has mostly disappeared is a stub, not a fix.
    if before.strip() and len(after) < len(before) * _SHRANK_TO:
        reasons.append(f"the patch removes {100 - int(100 * len(after) / len(before))}% "
                       "of the file")

    # 5. Ending early is not succeeding.
    if _exits_early(after) and not _exits_early(before):
        reasons.append("the patch makes the script exit before doing its work")

    if spec is not None:
        reasons += _scientific_reasons(before, after, spec)

    if reasons:
        logger.warning("Patch to %s refused: %s", filename or "a file", "; ".join(reasons))
    return GuardResult(not reasons, reasons)


def _scientific_reasons(before: str, after: str, spec) -> list[str]:
    """
    What the experiment's own design forbids, where it can be checked by
    reading the text rather than by judging intent.

    Only mechanical facts are checked: a name that was in the file and is no
    longer. Nothing here decides whether two implementations are scientifically
    equivalent -- that judgement cannot be made by matching strings, and
    pretending otherwise would be worse than not checking.
    """
    reasons: list[str] = []

    dropped_conditions = [c for c in spec.conditions if c in before and c not in after]
    if dropped_conditions:
        reasons.append("the patch removes the condition "
                       + ", ".join(sorted(dropped_conditions)))

    if spec.primary_metric and spec.primary_metric in before and spec.primary_metric not in after:
        reasons.append(f"the patch removes the primary outcome {spec.primary_metric}")

    if spec.study_type.value in before and spec.study_type.value not in after:
        reasons.append("the patch changes what kind of study this is")

    for contract in spec.required_outputs:
        name = contract.path.split("/")[-1]
        if name in before and name not in after:
            reasons.append(f"the patch stops writing {contract.path}")

    # The frozen pool is the ground truth of a controlled decision study: a
    # patch that builds its own pool instead of loading the frozen one has
    # replaced the thing every condition is supposed to share.
    if "CandidatePool.load" in before and "CandidatePool.load" not in after:
        reasons.append("the patch stops loading the frozen candidate pool")
    for guard_call in ("validate_curation", "parse_curation"):
        if guard_call in before and guard_call not in after:
            reasons.append(f"the patch removes the curation check ({guard_call})")
    if "check_unchanged" in before and "check_unchanged" not in after:
        reasons.append("the patch removes the check that the candidate pool did not change")

    return reasons


def _exits_early(source: str) -> bool:
    """A module-level `sys.exit(0)` or `exit(0)` before anything else runs."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef, ast.Expr)):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                name = getattr(node.value.func, "id", "") or getattr(node.value.func, "attr", "")
                if name == "exit":
                    return True
            continue
        break
    return False
