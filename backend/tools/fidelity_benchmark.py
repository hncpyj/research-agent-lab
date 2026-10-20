"""
Running a fidelity suite and counting what it got right, without adjusting it.

The gate has two ways to be wrong and they cost different things. Missing a
substitution lets a study answer a question nobody asked; blocking a faithful
rewording makes the gate something people route around, and a gate that is
routed around is not a gate. So nothing here reports a single accuracy number:
recall, precision, the false-block rate and the escalation rate are reported
separately, with their numerators and denominators, because they are traded
against each other and an average hides the trade.

Labels are pre-registered. A case whose verdict is right but whose failure code
is not is counted as detected and recorded as a code mismatch -- it is never
relabelled to match what came out.

    python -m tools.fidelity_benchmark v2
    python -m tools.fidelity_benchmark --cases <path to a labelled case file>
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL, NEEDS_HUMAN = "PASS", "FAIL", "NEEDS_HUMAN"
FAITHFUL, DRIFTED, AMBIGUOUS = "FAITHFUL", "DRIFTED", "AMBIGUOUS"

# Which protocol fields a case may override, and which of them are tuples.
_TUPLE_FIELDS = ("independent_variables", "dependent_variables", "conditions",
                 "held_constant", "secondary_metrics", "required_controls",
                 "known_confounds", "required_raw_fields")


def build_protocol(approved: dict, overrides: dict):
    """
    The protocol a case is checked against, with the case's edits applied.

    A controlled-decision study is built by the production builder. A study in
    a family this system has no scaffold for is assembled directly from the
    fields the case states: the fidelity gate compares an approved intent with
    a protocol and does not care whether anything can run it, and refusing to
    check a protocol because no scaffold implements it would put every domain
    but one out of reach of the evaluation.
    """
    from agents.experiment_agent import UnsupportedExperimentError, build_spec
    from agents.study_protocol import StudyType

    hypothesis = (approved.get("hypothesis") or "").strip()
    question = (approved.get("research_question") or "").strip()
    try:
        protocol = build_spec(hypothesis or question, {}, question)
    except UnsupportedExperimentError:
        protocol = _bare_protocol(hypothesis, question, overrides)

    changes: dict = {}
    for name, value in (overrides or {}).items():
        if name == "study_type":
            changes[name] = StudyType(value)
        elif name in _TUPLE_FIELDS:
            changes[name] = tuple(value)
        else:
            changes[name] = value
    return dataclasses.replace(protocol, **changes) if changes else protocol


def _bare_protocol(hypothesis: str, question: str, overrides: dict):
    """A protocol carrying only what the case says, for families with no scaffold."""
    from agents.study_protocol import (DatasetPolicy, OutputContract, StudyProtocol,
                                       StudyType)

    return StudyProtocol(
        study_type=StudyType.CONTROLLED_LLM,
        requires_training=False,
        dataset_policy=DatasetPolicy.NONE,
        research_question=question,
        hypothesis=hypothesis,
        independent_variables=tuple(overrides.get("independent_variables") or ()),
        dependent_variables=tuple(
            [overrides.get("primary_metric", "")] +
            list(overrides.get("secondary_metrics") or ())),
        held_constant=tuple(overrides.get("held_constant") or ()),
        conditions=tuple(overrides.get("conditions") or ()),
        primary_metric=overrides.get("primary_metric", ""),
        secondary_metrics=tuple(overrides.get("secondary_metrics") or ()),
        required_controls=tuple(overrides.get("required_controls") or ()),
        unit_of_analysis=overrides.get("unit_of_analysis", ""),
        causal_claim=overrides.get("causal_claim", ""),
        primary_estimand=overrides.get("primary_estimand", ""),
        support_if=overrides.get("support_if", ""),
        reject_if=overrides.get("reject_if", ""),
        required_outputs=(OutputContract(path="results/raw.jsonl", format="jsonl"),),
        scaffold_id="external",
    )

def run_case(case: dict) -> dict:
    """One labelled case through the production gate, recorded whatever it says."""
    from agents import intent_fidelity as fid

    approved_spec = case["approved_intent"]
    approved = fid.ApprovedIntent(
        research_question=approved_spec.get("research_question", ""),
        hypothesis=approved_spec.get("hypothesis", ""),
        structured=approved_spec.get("structured", {}) or {})
    protocol = build_protocol(approved_spec, case.get("protocol_overrides") or {})
    result = fid.check(protocol, approved=approved)

    codes = sorted({f.code for f in result.findings})
    expected_codes = sorted(case.get("expected_codes") or [])
    return {
        "case_id": case["case_id"],
        "category": case.get("category", ""),
        "label": case["label"],
        "expected_verdict": case["expected_verdict"],
        "verdict": result.status,
        "verdict_correct": result.status == case["expected_verdict"],
        "expected_codes": expected_codes,
        "codes": codes,
        "blocking_codes": result.failure_codes,
        "codes_match": bool(expected_codes) and set(expected_codes) <= set(codes),
        "intent_sources": result.sources,
        "unspecified": result.unspecified,
        "findings": [f.as_dict() for f in result.findings],
        "protocol_hash": protocol.protocol_hash,
        "rationale": case.get("rationale", ""),
    }


def score(rows: list[dict]) -> dict:
    """
    The confusion matrix, stated in the terms the gate is actually judged on.

    Positive means drift, because drift is what the gate exists to catch. A
    NEEDS_HUMAN on a drifted case is not a detection -- it did not block on
    scientific grounds -- but it is not a miss either, so it is counted in its
    own column rather than folded into one of theirs.
    """
    drifted = [r for r in rows if r["label"] == DRIFTED]
    faithful = [r for r in rows if r["label"] == FAITHFUL]
    ambiguous = [r for r in rows if r["label"] == AMBIGUOUS]

    true_positive = [r for r in drifted if r["verdict"] == FAIL]
    escalated_drift = [r for r in drifted if r["verdict"] == NEEDS_HUMAN]
    false_negative = [r for r in drifted if r["verdict"] == PASS]

    false_positive = [r for r in faithful if r["verdict"] == FAIL]
    false_block_needs_human = [r for r in faithful if r["verdict"] == NEEDS_HUMAN]
    true_negative = [r for r in faithful if r["verdict"] == PASS]

    escalated = [r for r in ambiguous if r["verdict"] == NEEDS_HUMAN]
    ambiguous_passed = [r for r in ambiguous if r["verdict"] == PASS]
    ambiguous_failed = [r for r in ambiguous if r["verdict"] == FAIL]

    def ratio(part, whole) -> str:
        return f"{len(part)}/{len(whole)}" if whole else "0/0"

    all_failed = [r for r in rows if r["verdict"] == FAIL]
    return {
        "n": len(rows),
        "true_positives": ratio(true_positive, drifted),
        "false_positives": ratio(false_positive, faithful),
        "true_negatives": ratio(true_negative, faithful),
        "false_negatives": ratio(false_negative, drifted),
        "drift_escalated_to_needs_human": ratio(escalated_drift, drifted),
        "needs_human_cases": sum(1 for r in rows if r["verdict"] == NEEDS_HUMAN),
        "detection_recall": ratio(true_positive, drifted),
        "precision": (f"{len(true_positive)}/{len(all_failed)}" if all_failed else "0/0"),
        "false_block_rate": ratio(false_positive + false_block_needs_human, faithful),
        "ambiguity_escalation_rate": ratio(escalated, ambiguous),
        "ambiguous_wrongly_passed": ratio(ambiguous_passed, ambiguous),
        "ambiguous_wrongly_failed": ratio(ambiguous_failed, ambiguous),
        "verdicts_as_pre_registered": ratio([r for r in rows if r["verdict_correct"]], rows),
        "code_mismatches": [r["case_id"] for r in rows
                            if r["expected_codes"] and not r["codes_match"]],
    }


def run(cases: list[dict]) -> tuple[list[dict], dict]:
    rows = [run_case(c) for c in cases]
    return rows, score(rows)


def _load(argv: list[str]) -> tuple[str, list[dict]]:
    if len(argv) > 1 and argv[1] == "--cases":
        payload = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        return Path(argv[2]).name, payload["cases"]
    version = argv[1] if len(argv) > 1 else "v2"
    from tools import research_log
    return f"benchmark_{version}", research_log.benchmark(version)["fidelity_cases"]


def main(argv: list[str]) -> int:
    name, cases = _load(argv)
    rows, totals = run(cases)
    print(f"# {name}: {len(rows)} cases\n")
    for row in rows:
        mark = "ok " if row["verdict_correct"] else "XX "
        print(f"{mark}{row['case_id']:<34} {row['label']:<9} "
              f"expected {row['expected_verdict']:<12} got {row['verdict']:<12} "
              f"{','.join(row['codes']) or '-'}")
    print()
    for key, value in totals.items():
        print(f"{key:<32} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
