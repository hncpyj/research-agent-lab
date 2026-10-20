"""
Running the Core Benchmark, N times, and keeping every attempt.

A single successful generation says nothing about reliability: the generator is
stochastic, and the interesting question is how often it works and how it fails
when it does not. So this runs a benchmark case a predetermined number of
times, records each attempt whether it succeeded or not, and reports
numerators and denominators rather than a percentage.

Nothing here reruns only the failures, drops a seed, or stops early because the
numbers look good. The repetition count is an argument, decided before the run.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent / "research_logs" / "raw"


@dataclass
class Attempt:
    """One independent pass through the whole path, success or not."""
    attempt: int
    seed: int
    status: str
    review_verdict: str = ""
    intent_fidelity: str = ""
    intent_fidelity_codes: list = field(default_factory=list)
    intent_fidelity_findings: int = 0
    protocol_hash: str = ""
    protocol_version: int = 0
    manifest_tier: str = ""
    generation_calls: int = 0
    generation_retries: int = 0
    first_pass_valid: bool | None = None
    conformance: str = ""
    conformance_rules: int = 0
    preflight: str = ""
    preflight_stages: list = field(default_factory=list)
    runtime: str = ""
    results_conformance: str = ""
    pool_fingerprint: str = ""
    pool_size: int = 0
    wall_clock_s: float = 0.0
    failures: list = field(default_factory=list)
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else ""


def run_case(case: dict, api_model, folder: Path, attempt: int, seed: int,
             num_trials: int = 2, execute: bool = True) -> Attempt:
    """
    One attempt at one benchmark case, from the hypothesis to the numbers.

    `execute` runs the trials with the mock provider afterwards: deterministic,
    no network, and never presented as a scientific effect -- it checks that
    the artifacts the model wrote can actually carry a run.
    """
    import subprocess
    import sys

    import config
    from agents import scientific_conformance, study_builder

    started = time.time()
    record = Attempt(attempt=attempt, seed=seed, status="not_started")

    outcome = study_builder.build(case["hypothesis"], api_model, folder,
                                  num_trials=num_trials, curator="mock-curator",
                                  overseer="mock-overseer", backend="mock",
                                  run_preflight=True)
    record.status = outcome.status.value
    record.wall_clock_s = round(time.time() - started, 1)

    if outcome.review is not None:
        record.review_verdict = outcome.review.verdict
    if getattr(outcome, "fidelity", None) is not None:
        record.intent_fidelity = outcome.fidelity.status
        record.intent_fidelity_codes = list(outcome.fidelity.failure_codes)
        record.intent_fidelity_findings = len(outcome.fidelity.findings)
        for finding in outcome.fidelity.findings:
            record.failures.append({"labels": [_fidelity_label(finding.code)],
                                    "detail": f"[{finding.code}] {finding.detail}",
                                    "detected_at": "intent_fidelity",
                                    "would_invalidate": "yes"})
    if outcome.protocol is not None:
        record.protocol_hash = outcome.protocol.protocol_hash
        record.protocol_version = outcome.protocol.protocol_version
    if outcome.manifest is not None:
        record.manifest_tier = outcome.manifest.execution_tier.value
    if outcome.generation is not None:
        record.generation_calls = outcome.generation.calls
        # One call per artifact is the first pass; anything beyond it is a retry.
        expected = case.get("expected_first_pass_calls", 9)
        record.generation_retries = max(0, outcome.generation.calls - expected)
        record.first_pass_valid = record.generation_retries == 0
        for problem in outcome.generation.problems:
            record.failures.append({"labels": ["MALFORMED_GENERATION"], "detail": problem,
                                    "detected_at": "generation",
                                    "would_invalidate": "no", "recovered": False})
        for event in outcome.generation.recovered:
            # Recovered, but recorded: a generator that needs a retry three
            # times in five is not the same generator as one that does not.
            labels = (["TRUNCATED_OUTPUT"] if "cut short" in event["problem"]
                      else ["MALFORMED_GENERATION"])
            record.failures.append({"labels": labels,
                                    "detail": f"{event['artifact']} ({event['item']}): "
                                              f"{event['problem']}",
                                    "detected_at": "generation/validation",
                                    "would_invalidate": "no", "recovered": True})
    if outcome.conformance is not None:
        record.conformance = outcome.conformance.verdict
        record.conformance_rules = len(outcome.conformance.checked)
        for violation in outcome.conformance.violations:
            record.failures.append({"labels": _labels_for(violation.rule),
                                    "detail": f"{violation.artifact}: {violation.message}",
                                    "detected_at": "scientific_conformance",
                                    "would_invalidate": "yes"})
    if outcome.preflight is not None:
        record.preflight = "PASS" if outcome.preflight.passed else "FAIL"
        record.preflight_stages = list(outcome.preflight.ran)
        for failure in outcome.preflight.failures:
            record.failures.append({"labels": [_software_label(failure.stage)],
                                    "detail": f"{failure.file}: {failure.message}",
                                    "detected_at": f"preflight/{failure.stage}"})

    pool_path = folder / "candidate_pool.json"
    if pool_path.exists():
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        record.pool_fingerprint = pool.get("fingerprint", "")
        record.pool_size = len(pool.get("candidates", []))

    if record.status == "generation_blocked_resource":
        record.failures.append({"labels": ["RESOURCE_EXHAUSTION", "SAFE_HALT"],
                                "detail": outcome.notes[-1] if outcome.notes else "",
                                "detected_at": "generation",
                                "would_invalidate": "no"})
    if record.status in ("scientific_verification_failed", "software_verification_failed",
                         "generation_failed_model_output"):
        record.failures.append({"labels": ["SAFE_HALT"], "detail": outcome.summary(),
                                "detected_at": record.status, "would_invalidate": "no"})

    if not execute or record.status != "verified_ready":
        return record

    done = subprocess.run([sys.executable, "run_experiment.py", "--config", "config.yaml"],
                          cwd=str(folder), capture_output=True, text=True, timeout=600,
                          env={"PATH": "", "PYTHONPATH": str(folder),
                               "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": "C:/Windows"})
    record.runtime = "PASS" if done.returncode == 0 else "FAIL"
    if done.returncode != 0:
        record.failures.append({"labels": ["RUNTIME_ERROR"],
                                "detail": (done.stderr.strip().splitlines() or [""])[-1],
                                "detected_at": "runtime"})
        record.wall_clock_s = round(time.time() - started, 1)
        return record

    results = scientific_conformance.verify_results(folder, outcome.protocol)
    record.results_conformance = results.verdict
    for violation in results.violations:
        record.failures.append({"labels": _labels_for(violation.rule),
                                "detail": f"{violation.artifact}: {violation.message}",
                                "detected_at": "results_conformance",
                                "would_invalidate": "yes"})
    record.wall_clock_s = round(time.time() - started, 1)
    return record


def _labels_for(rule: str) -> list[str]:
    """The taxonomy labels a conformance rule maps to."""
    return {
        "conditions": ["UNDECLARED_CONDITION"],
        "outcomes": ["METRIC_SUBSTITUTION"],
        "ground_truth": ["GROUND_TRUTH_VIOLATION"],
        "randomisation": ["CONFOUND"],
        "apparatus": ["INTERFACE_ERROR"],
        "outcome_fields": ["METRIC_SUBSTITUTION"],
        "raw_fields": ["PROTOCOL_ERROR"],
        "wording": ["MANIPULATION_LEAKAGE"],
        "protocol_hash": ["INTENT_DRIFT"],
        "protocol_state": ["PROTOCOL_ERROR"],
        "summary": ["METRIC_SUBSTITUTION"],
        "outputs": ["RUNTIME_ERROR"],
        "overseer_view": ["GROUND_TRUTH_VIOLATION"],
    }.get(rule, ["UNKNOWN"])


def _fidelity_label(code: str) -> str:
    """The taxonomy label an intent-fidelity code maps to."""
    return {
        "INTERVENTION_CHANGED": "INTENT_DRIFT",
        "CONDITION_DROPPED": "UNDECLARED_CONDITION",
        "COMPARATOR_CHANGED": "UNDECLARED_CONDITION",
        "PRIMARY_OUTCOME_CHANGED": "METRIC_SUBSTITUTION",
        "SECONDARY_OUTCOME_DROPPED": "METRIC_SUBSTITUTION",
        "HELD_CONSTANT_REMOVED": "CONFOUND",
        "STUDY_TYPE_CHANGED": "WRONG_EXPERIMENT_FAMILY",
        "UNIT_OF_ANALYSIS_CHANGED": "METHODOLOGY_ERROR",
        "CLAIM_SCOPE_EXPANDED": "INTENT_DRIFT",
        "CLAIM_SCOPE_WEAKENED": "INTENT_DRIFT",
        "REQUIRED_CONTROL_DROPPED": "CONFOUND",
        "AMBIGUOUS_MAPPING": "UNKNOWN",
    }.get(code, "UNKNOWN")


def _software_label(stage: str) -> str:
    return {"compile": "MALFORMED_GENERATION", "contract": "INTERFACE_ERROR",
            "imports": "IMPORT_ERROR", "dependencies": "DEPENDENCY_ERROR",
            "smoke": "RUNTIME_ERROR", "spec": "PROTOCOL_ERROR"}.get(stage, "UNKNOWN")


def repeat(case: dict, api_model, workspace: Path, repetitions: int,
           seeds: list[int] | None = None, num_trials: int = 2,
           execute: bool = True) -> list[Attempt]:
    """
    Run one case `repetitions` times and keep every attempt.

    The seeds are fixed in advance so the set of attempts is decided before any
    of them is seen. A failed attempt stays in the record.
    """
    seeds = seeds or list(range(1, repetitions + 1))
    attempts = []
    for index, seed in enumerate(seeds[:repetitions], start=1):
        folder = Path(workspace) / f"attempt_{index:02d}"
        try:
            attempt = run_case(case, api_model, folder, index, seed,
                               num_trials=num_trials, execute=execute)
        except Exception as exc:                 # an attempt that crashed is an attempt
            attempt = Attempt(attempt=index, seed=seed, status="harness_error",
                              notes=f"{type(exc).__name__}: {exc}",
                              failures=[{"labels": ["UNKNOWN"], "detail": str(exc)[:300],
                                         "detected_at": "harness"}])
        attempts.append(attempt)
        print(f"  attempt {index}/{repetitions}: {attempt.status} "
              f"(conformance={attempt.conformance or '-'}, preflight={attempt.preflight or '-'}, "
              f"runtime={attempt.runtime or '-'}, {attempt.wall_clock_s}s)")
    return attempts


def aggregate(attempts: list[Attempt]) -> dict:
    """
    Numerators and denominators. No percentage stands alone here: with five
    attempts, "80%" and "4/5" carry very different amounts of information.
    """
    total = len(attempts) or 1

    def count(predicate) -> int:
        return sum(1 for a in attempts if predicate(a))

    verified = count(lambda a: a.status == "verified_ready")
    halted = count(lambda a: a.status in ("generation_blocked_resource",
                                          "generation_failed_model_output",
                                          "scientific_verification_failed",
                                          "software_verification_failed",
                                          "design_rejected"))
    labels: dict[str, int] = {}
    recovered_labels: dict[str, int] = {}
    for attempt in attempts:
        for failure in attempt.failures:
            target = recovered_labels if failure.get("recovered") else labels
            for label in failure.get("labels", []):
                target[label] = target.get(label, 0) + 1

    return {
        "attempts": len(attempts),
        "valid_completion": f"{count(lambda a: a.results_conformance == 'PASS')}/{total}",
        "verified_ready": f"{verified}/{total}",
        "safe_halt": f"{halted}/{total}",
        "silent_scientific_failure": f"{count(lambda a: a.runtime == 'PASS' and a.results_conformance == 'FAIL')}/{total}",
        "false_block": f"{count(lambda a: a.review_verdict == 'FAIL')}/{total}",
        "methodology_pass": f"{count(lambda a: a.review_verdict == 'PASS')}/{total}",
        "intent_fidelity_pass": f"{count(lambda a: a.intent_fidelity == 'PASS')}/{total}",
        "intent_fidelity_fail": f"{count(lambda a: a.intent_fidelity == 'FAIL')}/{total}",
        "intent_fidelity_needs_human": f"{count(lambda a: a.intent_fidelity == 'NEEDS_HUMAN')}/{total}",
        "first_pass_generation_valid": f"{count(lambda a: a.first_pass_valid is True)}/{total}",
        "retry_recovered": f"{count(lambda a: a.first_pass_valid is False and a.status == 'verified_ready')}/{count(lambda a: a.first_pass_valid is False) or 0}",
        "scientific_conformance_pass": f"{count(lambda a: a.conformance == 'PASS')}/{total}",
        "software_preflight_pass": f"{count(lambda a: a.preflight == 'PASS')}/{total}",
        "runtime_pass": f"{count(lambda a: a.runtime == 'PASS')}/{total}",
        "results_conformance_pass": f"{count(lambda a: a.results_conformance == 'PASS')}/{total}",
        "distinct_pool_fingerprints": len({a.pool_fingerprint for a in attempts if a.pool_fingerprint}),
        "mean_model_calls": round(sum(a.generation_calls for a in attempts) / total, 1),
        "mean_wall_clock_s": round(sum(a.wall_clock_s for a in attempts) / total, 1),
        "failure_taxonomy_counts": dict(sorted(labels.items())),
        "recovered_failure_counts": dict(sorted(recovered_labels.items())),
    }


def save_raw(attempts: list[Attempt], name: str) -> Path:
    """
    Keep every attempt where a later aggregate can be recomputed from it.

    A summary whose raw records are gone is a claim, not evidence.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for attempt in attempts:
            handle.write(json.dumps(attempt.as_dict(), ensure_ascii=False) + "\n")
    return path
