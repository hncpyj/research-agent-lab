"""Protocol adapter for the approved declared-dataset analysis path.

This module translates records that have already passed the data, hypothesis,
and plan approval gates into the common scientific authority.  It does not
choose a statistic, comparator, threshold, or variable.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agents.intent_fidelity import ApprovedIntent
from agents.study_protocol import (DatasetPolicy, OutputContract, StudyProtocol,
                                   StudyType)


class DatasetProtocolIncomplete(ValueError):
    """The approved records do not state enough science to freeze a protocol."""


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rule_outputs(test: dict) -> list[str]:
    outputs: list[str] = []
    for field in ("support_if", "reject_if"):
        rule = test.get(field, "")
        parts = re.split(r"\s+(?:AND|OR)\s+", rule.strip(), flags=re.I)
        parsed = []
        for part in parts:
            match = re.match(r"^\s*([a-z_]+)\s*(?:>=|<=|>|<)\s*-?\d+(?:\.\d+)?\s*$",
                             part, re.I)
            if not match:
                raise DatasetProtocolIncomplete(
                    f"approved test {test.get('id', '?')} has an unreadable {field}: {part!r}")
            parsed.append(match.group(1))
        outputs.extend(parsed)
    return list(dict.fromkeys(outputs))


def _selector_conditions(tests: list[dict]) -> tuple[str, ...]:
    """Conditions explicitly named by approved selectors; no synthetic arms."""
    found: list[str] = []
    for test in tests:
        for key, value in (test.get("typed_params") or {}).items():
            if key not in {"pair", "pair_y", "groups", "classes"}:
                continue
            _, _, values = str(value).partition(":")
            if not values:
                values = str(value)
            found.extend(v.strip() for v in values.split(",") if v.strip())
    return tuple(dict.fromkeys(found))


def _scientific_tests(tests: list[dict]) -> list[dict]:
    kept = []
    for test in tests:
        if test.get("problems"):
            raise DatasetProtocolIncomplete(
                f"approved test {test.get('id', '?')} still has validation problems"
            )
        required = ("id", "hypothesis", "compares", "block", "typed_params",
                    "support_if", "reject_if")
        missing = [name for name in required if not test.get(name)]
        if missing:
            raise DatasetProtocolIncomplete(
                f"approved test {test.get('id', '?')} is missing {', '.join(missing)}"
            )
        kept.append({
            "id": test["id"],
            "hypothesis": test["hypothesis"],
            "compares": test["compares"],
            "block": test["block"],
            "params": dict(test["typed_params"]),
            "support_if": test["support_if"],
            "reject_if": test["reject_if"],
            "threats": test.get("threats", ""),
            "outputs": _rule_outputs(test),
        })
    if not kept:
        raise DatasetProtocolIncomplete("the approved analysis plan contains no tests")
    return kept


def build_protocol(question: str, hypotheses: dict, audit: dict, tests: list[dict],
                   plan_version: int, dataset_path: Path) -> tuple[StudyProtocol, ApprovedIntent]:
    """Return the protocol and the exact human-approved authority it came from."""
    selected_ids = list(hypotheses.get("selected") or ())
    selected = [h for h in hypotheses.get("hypotheses", ()) if h.get("id") in selected_ids]
    if not selected or len(selected) != len(selected_ids):
        raise DatasetProtocolIncomplete("the selected hypotheses cannot be recovered")
    if not question.strip():
        raise DatasetProtocolIncomplete("the approved research question is empty")
    dataset_path = Path(dataset_path)
    if not dataset_path.is_file():
        raise DatasetProtocolIncomplete(f"the audited dataset is unavailable: {dataset_path}")

    scientific_tests = _scientific_tests(tests)
    output_names = list(dict.fromkeys(
        output for test in scientific_tests for output in test["outputs"]))
    if not output_names:
        raise DatasetProtocolIncomplete("the approved decision rules name no result fields")

    layout = dict(audit.get("layout") or {})
    layout_without_path = {k: v for k, v in layout.items() if k != "path"}
    dataset_identity = {
        "source": audit.get("source") or "",
        "sha256": _file_sha256(dataset_path),
        "layout_sha256": _digest(layout_without_path),
    }
    if not dataset_identity["source"]:
        raise DatasetProtocolIncomplete("the data audit records no source identity")

    plan = {"plan_version": int(plan_version), "tests": scientific_tests}
    hypothesis_text = "\n".join(
        f"{h['id']}: {h.get('statement', '').strip()}" for h in selected)
    variables = tuple(dict.fromkeys(
        f"{key}={value}"
        for test in scientific_tests
        for key, value in test["params"].items()
        if key not in {"bootstrap", "n_bootstrap", "seed", "stat"}
    ))
    if not variables:
        raise DatasetProtocolIncomplete("the approved plan binds no audited variables")

    unit = audit.get("units") or {}
    unit_label = str(unit.get("kind") or unit.get("column") or "").strip()
    if not unit_label:
        raise DatasetProtocolIncomplete("the data audit does not state the unit of analysis")

    protocol = StudyProtocol(
        study_type=StudyType.DATASET_ANALYSIS,
        requires_training=False,
        dataset_policy=DatasetPolicy.REQUIRED,
        research_question=question.strip(),
        hypothesis=hypothesis_text,
        causal_claim="",
        unit_of_analysis=unit_label,
        unit_of_randomization="",
        independent_variables=variables,
        dependent_variables=tuple(output_names),
        held_constant=("audited dataset identity", "approved analysis plan", "analysis block definitions"),
        conditions=_selector_conditions(tests),
        ground_truth=f"audited dataset from {dataset_identity['source']}",
        sampling=str(unit.get("rule") or "the rows accepted by the audited panel layout"),
        trial_structure="one deterministic analysis result per approved TEST block",
        randomization="",
        counterbalancing="",
        primary_metric=output_names[0],
        secondary_metrics=tuple(output_names[1:]),
        primary_estimand="; ".join(f"{t['id']}: {t['compares']}" for t in scientific_tests),
        support_if="; ".join(f"{t['id']}: {t['support_if']}" for t in scientific_tests),
        reject_if="; ".join(f"{t['id']}: {t['reject_if']}" for t in scientific_tests),
        known_confounds=tuple(t["threats"] for t in scientific_tests if t.get("threats")),
        required_controls=("validated data audit", "human-approved analysis plan"),
        required_raw_fields=("test_id", "block", "params", "outputs"),
        measurement={name: [name] for name in output_names},
        required_outputs=tuple(
            OutputContract(path=f"results/{t['id']}.json", format="json",
                           required_keys=("test_id", "block", "params", "outputs"))
            for t in scientific_tests
        ),
        allowed_agent_actions=(),
        forbidden_agent_actions=("change the approved dataset", "change an approved test block",
                                 "change a variable binding", "change a decision rule"),
        resource_constraints={},
        dataset_identity=dataset_identity,
        analysis_plan=plan,
        scaffold_id="analysis_plan",
    )

    def entries(values, prefix):
        return [{"display_name": value,
                 "concept_id": f"dataset:{prefix}:{_digest(value)[:16]}"}
                for value in values]

    structured = {
        "interventions": entries(protocol.independent_variables, "variable"),
        "conditions": entries(protocol.conditions, "condition"),
        "primary_outcome": entries((protocol.primary_metric,), "output")[0],
        "secondary_outcomes": entries(protocol.secondary_metrics, "output"),
        "held_constant": entries(protocol.held_constant, "constant"),
        "unit_of_analysis": {"display_name": protocol.unit_of_analysis,
                             "concept_id": f"dataset:unit:{_digest(protocol.unit_of_analysis)[:16]}"},
        # Dataset/plan are deliberately carried even though the general text
        # intent reader has no slots for them; the dataset adapter checks them.
        "dataset_identity": dataset_identity,
        "analysis_plan": plan,
    }
    approved = ApprovedIntent(
        hypothesis=hypothesis_text,
        research_question=question.strip(),
        structured=structured,
        approved_by="declared-dataset hypothesis and plan approval gates",
        domain="dataset_analysis",
    )
    return protocol, approved
