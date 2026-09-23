"""
Whether what was built is the study that was approved.

This is a different question from "does the code run", and it used to have no
answer at all. A program that compiles, imports, executes and writes a
plausible summary can still be measuring something nobody asked about — that is
precisely what happened: a study of adversarial curation ran happily as a
MiniGrid agent.

So conformance is its own gate, with its own inputs:

    the frozen StudyProtocol      what must be established
    the BuildManifest             how it was to be implemented
    the artifacts on disk         what was actually built

and its own consequence. A conformance failure is never sent to the repair
loop: a repair makes code run, and code running is not the problem. The
violating artifact is regenerated from the frozen protocol instead, and if
fixing it would mean changing the protocol, the run stops and asks for a new
protocol version — because at that point the disagreement is scientific, and
no amount of editing files settles it.

Only mechanically checkable properties are checked here. Whether two designs
are scientifically equivalent is not one of them, and claiming otherwise would
be worse than not checking.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

PASS, FAIL = "PASS", "FAIL"


@dataclass
class Violation:
    rule: str
    artifact: str
    message: str

    def as_dict(self) -> dict:
        return {"rule": self.rule, "artifact": self.artifact, "message": self.message}


@dataclass
class Conformance:
    verdict: str
    violations: list[Violation] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    @property
    def artifacts_to_regenerate(self) -> list[str]:
        """
        Which generated artifacts to write again, from the protocol.

        A violation in a deterministic artifact or in the apparatus is not
        something regeneration can fix -- it means trusted code or the plan is
        wrong, which is a bug here, not a bad answer from a model.
        """
        return sorted({v.artifact for v in self.violations
                       if v.artifact in ("candidate_pool.json", "prompts.json")})

    @property
    def needs_new_protocol(self) -> bool:
        """Whether the disagreement is with the science itself."""
        return any(v.rule in ("protocol_hash", "conditions", "outcomes")
                   for v in self.violations)

    def summary(self) -> str:
        if self.passed:
            return f"Scientific conformance passed ({len(self.checked)} rules)."
        first = self.violations[0]
        return f"Scientific conformance failed: {first.message}"

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "checked": self.checked,
                "violations": [v.as_dict() for v in self.violations]}


def verify(folder: Path | str, protocol=None, manifest=None) -> Conformance:
    """Check the built study against the protocol it was built for."""
    folder = Path(folder)
    from agents.build_manifest import BuildManifest
    from agents.study_protocol import StudyProtocol

    protocol = protocol or StudyProtocol.read(folder)
    manifest = manifest or BuildManifest.read(folder)
    if protocol is None:
        return Conformance(FAIL, [Violation("protocol", "", "there is no protocol to check "
                                                            "this study against")])
    if manifest is None:
        return Conformance(FAIL, [Violation("manifest", "", "there is no build manifest")])

    result = Conformance(PASS)
    _check_plan_matches_protocol(protocol, manifest, result)
    if protocol.scaffold_id == "controlled_llm":
        _check_controlled_llm(folder, protocol, result)
    if result.violations:
        result.verdict = FAIL
    return result


def _check_plan_matches_protocol(protocol, manifest, result: Conformance) -> None:
    result.checked.append("the plan was made for this protocol")
    if not manifest.matches(protocol):
        result.violations.append(Violation(
            "protocol_hash", "build_manifest.json",
            f"the plan was made for protocol {manifest.protocol_hash} but the protocol "
            f"here is {protocol.protocol_hash}: the science changed after it was planned"))
    result.checked.append("the protocol is frozen")
    if not protocol.frozen:
        result.violations.append(Violation(
            "protocol_state", "study_protocol.json",
            f"the protocol is {protocol.status.value}, not frozen; nothing should have "
            "been built from it"))


# --- the controlled-decision family -------------------------------------------------

def _check_controlled_llm(folder: Path, protocol, result: Conformance) -> None:
    config = _read_config(folder, result)

    # 1. The conditions and outcomes the study will actually run.
    result.checked.append("conditions match the protocol")
    stated = tuple(config.get("conditions") or ())
    if stated and stated != tuple(protocol.conditions):
        result.violations.append(Violation(
            "conditions", "config.yaml",
            f"the study would run {list(stated)} but the protocol compares "
            f"{list(protocol.conditions)}"))

    result.checked.append("outcomes match the protocol")
    outcomes = config.get("outcomes") or {}
    if outcomes.get("primary") and outcomes["primary"] != protocol.primary_metric:
        result.violations.append(Violation(
            "outcomes", "config.yaml",
            f"the primary outcome would be {outcomes['primary']!r}, not "
            f"{protocol.primary_metric!r}"))
    secondary = tuple(outcomes.get("secondary") or ())
    if secondary and secondary != tuple(protocol.secondary_metrics):
        result.violations.append(Violation(
            "outcomes", "config.yaml",
            f"the secondary outcomes would be {list(secondary)}, not "
            f"{list(protocol.secondary_metrics)}"))

    # 2. The ground truth: one pool, frozen, shared by every condition.
    result.checked.append("the candidate pool is frozen and shared")
    pool = _read_pool(folder, result)
    if pool is not None:
        if not pool.get("fingerprint"):
            result.violations.append(Violation(
                "ground_truth", "candidate_pool.json",
                "the pool carries no fingerprint, so an edit to a candidate could not "
                "be detected"))
        shown_per_trial = int((config.get("candidate_pool") or {}).get("shown_per_trial", 0))
        if shown_per_trial and shown_per_trial >= len(pool.get("candidates", [])):
            result.violations.append(Violation(
                "ground_truth", "config.yaml",
                f"every trial would show {shown_per_trial} of "
                f"{len(pool.get('candidates', []))} candidates: with nothing withheld "
                "there is no curation to compare"))

    # 3. The randomisation the protocol requires.
    result.checked.append("target assignment and counterbalancing follow the protocol")
    target = config.get("target") or {}
    if protocol.randomization and not target.get("randomized"):
        result.violations.append(Violation(
            "randomisation", "config.yaml",
            "the protocol randomises the target per trial; the config does not"))
    if protocol.counterbalancing and not target.get("counterbalance"):
        result.violations.append(Violation(
            "randomisation", "config.yaml",
            "the protocol counterbalances the target; the config does not"))

    # 4. What the apparatus is asked to guarantee. These are properties of the
    #    trusted code, so a violation here means the apparatus was replaced.
    _check_apparatus(folder, protocol, result)

    # 5. The wording: one overseer prompt, and a curator that is told what it
    #    may not do.
    _check_wording(folder, protocol, result)


def _check_apparatus(folder: Path, protocol, result: Conformance) -> None:
    expected = {
        "curation.py": ("parse_curation",),
        "overseer.py": ("parse_decision",),
        "run_experiment.py": ("check_unchanged", "presentation_order", "assign_target",
                              "TrialLog", "results_dir"),
        "evaluate.py": ("summarise", "TrialLog"),
    }
    result.checked.append("the apparatus that enforces the design is present")
    for name, needed in expected.items():
        path = folder / name
        if not path.exists():
            result.violations.append(Violation("apparatus", name, f"{name} is missing"))
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for symbol in needed:
            if symbol not in source:
                result.violations.append(Violation(
                    "apparatus", name,
                    f"{name} no longer uses {symbol}: the mechanism the protocol relies "
                    "on has been replaced"))

    result.checked.append("selection and approval are recorded separately")
    choice_set = folder / "choice_set.py"
    if choice_set.exists():
        source = choice_set.read_text(encoding="utf-8", errors="replace")
        for field_name in ("selected_option", "explicit_approval", "reject_all",
                           "request_more_options"):
            if field_name not in source:
                result.violations.append(Violation(
                    "outcome_fields", "choice_set.py",
                    f"{field_name} is not recorded, and the protocol measures it"))
    else:
        result.violations.append(Violation("apparatus", "choice_set.py",
                                           "the rules module is missing"))

    result.checked.append("every required raw field is recorded")
    if choice_set.exists():
        source = choice_set.read_text(encoding="utf-8", errors="replace")
        missing = [f for f in protocol.required_raw_fields if f not in source]
        if missing:
            result.violations.append(Violation(
                "raw_fields", "choice_set.py",
                f"the protocol requires {', '.join(missing)} in every trial record; "
                "the log does not carry them"))


def _check_wording(folder: Path, protocol, result: Conformance) -> None:
    path = folder / "prompts.json"
    result.checked.append("the curator is told what it may not do")
    if not path.exists():
        result.violations.append(Violation("wording", "prompts.json", "prompts.json is missing"))
        return
    try:
        wording = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.violations.append(Violation("wording", "prompts.json",
                                           f"prompts.json does not parse: {exc.msg}"))
        return

    adversarial = (wording.get("adversarial_curation") or "").lower()
    if adversarial and not any(word in adversarial for word in
                               ("not change", "do not change", "cannot change", "without changing",
                                "not reword", "may not", "must not", "no option's text")):
        result.violations.append(Violation(
            "wording", "prompts.json",
            "the adversarial curator is not told that it may not change or invent "
            "candidates, which is the one thing the protocol forbids it"))

    result.checked.append("one overseer prompt serves every condition")
    overseer = wording.get("overseer_prompt") or ""
    for condition in protocol.conditions:
        if condition.replace("_", " ") in overseer.lower() or condition in overseer:
            result.violations.append(Violation(
                "wording", "prompts.json",
                f"the overseer's prompt mentions the condition {condition}: the overseer "
                "must not be able to tell which condition it is in"))


def _read_config(folder: Path, result: Conformance) -> dict:
    path = folder / "config.yaml"
    if not path.exists():
        result.violations.append(Violation("config", "config.yaml", "config.yaml is missing"))
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        result.violations.append(Violation("config", "config.yaml",
                                           f"config.yaml does not parse: {exc}"))
        return {}


def _read_pool(folder: Path, result: Conformance) -> dict | None:
    path = folder / "candidate_pool.json"
    if not path.exists():
        result.violations.append(Violation("ground_truth", "candidate_pool.json",
                                           "the candidate pool is missing"))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.violations.append(Violation("ground_truth", "candidate_pool.json",
                                           f"the pool does not parse: {exc.msg}"))
        return None


# --- checking the results a run produced ---------------------------------------------

def verify_results(folder: Path | str, protocol=None) -> Conformance:
    """
    The same question, asked of what a run actually produced: are the trials
    what the protocol said they would be, and is the summary derived from them?
    """
    folder = Path(folder)
    from agents.study_protocol import StudyProtocol

    protocol = protocol or StudyProtocol.read(folder)
    result = Conformance(PASS)
    if protocol is None:
        return Conformance(FAIL, [Violation("protocol", "", "no protocol to check against")])

    results_dir = folder / "results"
    raw = results_dir / "raw_trials.jsonl"
    summary_file = results_dir / "summary_metrics.json"

    result.checked.append("the required outputs exist")
    for path in (raw, summary_file):
        if not path.exists():
            result.violations.append(Violation("outputs", path.name,
                                               f"{path.name} was not produced"))
    if result.violations:
        result.verdict = FAIL
        return result

    trials = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    summary = json.loads(summary_file.read_text(encoding="utf-8"))

    result.checked.append("every trial carries every required field")
    for trial in trials[:200]:
        missing = [f for f in protocol.required_raw_fields if f not in trial]
        if missing:
            result.violations.append(Violation(
                "raw_fields", "results/raw_trials.jsonl",
                f"a trial is missing {', '.join(missing)}"))
            break

    result.checked.append("only the protocol's conditions were run")
    ran = {t.get("condition") for t in trials}
    unexpected = ran - set(protocol.conditions)
    if unexpected:
        result.violations.append(Violation(
            "conditions", "results/raw_trials.jsonl",
            f"the trials include condition(s) {', '.join(sorted(unexpected))}, which the "
            "protocol does not name"))
    if trials and set(protocol.conditions) - ran:
        result.violations.append(Violation(
            "conditions", "results/raw_trials.jsonl",
            f"condition(s) {', '.join(sorted(set(protocol.conditions) - ran))} never ran"))

    result.checked.append("one pool across every condition")
    if len({t.get("pool_fingerprint") for t in trials}) > 1:
        result.violations.append(Violation(
            "ground_truth", "results/raw_trials.jsonl",
            "the trials were run against more than one candidate pool"))

    result.checked.append("no candidate outside the pool was shown")
    for trial in trials[:200]:
        pool_ids = set(trial.get("candidate_pool_ids") or ())
        shown = set(trial.get("shown_candidate_ids") or ())
        if not shown <= pool_ids:
            result.violations.append(Violation(
                "ground_truth", "results/raw_trials.jsonl",
                f"trial {trial.get('trial_id')} showed {', '.join(sorted(shown - pool_ids))}, "
                "which is not in the pool"))
            break
        if trial.get("selected_option") and trial["selected_option"] not in shown:
            result.violations.append(Violation(
                "overseer_view", "results/raw_trials.jsonl",
                f"trial {trial.get('trial_id')} selected {trial['selected_option']}, which "
                "was not shown to the overseer"))
            break

    result.checked.append("the summary is derived from the trials")
    from tools.choice_set import summarise

    recomputed = summarise(trials)
    for key in ("target_selection_rate", "explicit_approval_rate", "reject_rate",
                "request_more_options_rate"):
        if key not in summary:
            result.violations.append(Violation("summary", "results/summary_metrics.json",
                                               f"{key} is missing"))
        elif abs(float(summary[key]) - float(recomputed[key])) > 1e-9:
            result.violations.append(Violation(
                "summary", "results/summary_metrics.json",
                f"{key} is {summary[key]}, but the trials give {recomputed[key]}: the "
                "summary is not derived from the raw record"))
    if summary.get("num_trials_per_condition") != recomputed["num_trials_per_condition"]:
        result.violations.append(Violation(
            "summary", "results/summary_metrics.json",
            "the trial counts per condition do not match the raw record"))

    if result.violations:
        result.verdict = FAIL
    return result
