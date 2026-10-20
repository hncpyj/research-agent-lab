"""
Stage S7 — results against the plan.

One row per planned test, with the verdict the pre-registered decision rule
gives on the numbers the analysis wrote, and the file and keys each number
came from; plus one row per hypothesis or question part that could not be
tested. Computed, not written by a model. This table is the only source the
report (S8) may draw results from.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.analysis_plan import evaluate_rule, parse_rule

ESTIMATE_KEYS = ("mean", "difference", "coef", "r", "disagreement_share", "median", "share_rising",
                 "share_stalled", "share_reversed", "share_saturated", "mean_slope", "median_slope",
                 "share_rising_ci", "share_falling_ci", "mean_first", "mean_second")
N_KEYS = ("n_units", "n_series", "n_obs", "n_first", "n_second")


def _rule_keys(rule: str) -> list[str]:
    try:
        return [k for k, _, _ in parse_rule(rule)[1]]
    except ValueError:
        return []


def build(plan: dict, hypotheses: dict, folder: Path, degradations: list[dict]) -> dict:
    rows, n = [], 0
    for test in plan["tests"]:
        n += 1
        path = folder / "results" / f"{test['id']}.json"
        row = {"id": f"R{n}", "test": test["id"], "hypothesis": test["hypothesis"], "compares": test["compares"],
               "block": test["block"], "support_if": test["support_if"], "reject_if": test["reject_if"],
               "source": f"results/{test['id']}.json", "values": {}, "notes": [], "threats": test.get("threats", "")}
        if not path.exists():
            row.update(verdict="undetermined", reason="the analysis wrote no result for this test")
            rows.append(row)
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("error"):
            row.update(verdict="undetermined", reason=f"the analysis failed: {record['error']}")
            rows.append(row)
            continue
        outputs = record.get("outputs", {})
        shown = [k for k in (*_rule_keys(test["support_if"]), *_rule_keys(test["reject_if"]),
                             *ESTIMATE_KEYS, "ci_low", "ci_high", *N_KEYS, "p", "t_p", "wilcoxon_p",
                             "mannwhitney_p") if k in outputs]
        row["values"] = {k: outputs[k] for k in dict.fromkeys(shown)}
        row["notes"] = record.get("notes", [])
        support = evaluate_rule(test["support_if"], outputs)
        reject = evaluate_rule(test["reject_if"], outputs)
        if support is None or reject is None:
            row.update(verdict="undetermined", reason="an output the decision rule needs was not produced "
                                                      "(too few countries for an estimate)")
        elif support:
            row.update(verdict="supported", reason=f"SUPPORT_IF holds: {test['support_if']}")
        elif reject:
            row.update(verdict="rejected", reason=f"REJECT_IF holds: {test['reject_if']}")
        else:
            row.update(verdict="undetermined", reason="neither SUPPORT_IF nor REJECT_IF holds")
        rows.append(row)

    selected = set(hypotheses.get("selected", []))
    for h in hypotheses.get("hypotheses", []):
        if not h.get("testable"):
            n += 1
            rows.append({"id": f"R{n}", "test": None, "hypothesis": h["id"], "compares": h["statement"],
                         "verdict": "untestable", "reason": "; ".join(h.get("problems", [])), "values": {},
                         "source": "hypothesis check (S3)", "notes": []})
        elif h["id"] in selected and h.get("cannot_test"):
            n += 1
            rows.append({"id": f"R{n}", "test": None, "hypothesis": h["id"], "compares": h["cannot_test"],
                         "verdict": "untestable", "reason": "the data has no variable for this", "values": {},
                         "source": "hypothesis (CANNOT_TEST)", "notes": []})

    by_hypothesis = {}
    for row in rows:
        if row["test"]:
            by_hypothesis.setdefault(row["hypothesis"], []).append(row["verdict"])
    summary = {}
    for hid, verdicts in by_hypothesis.items():
        unique = set(verdicts)
        summary[hid] = verdicts[0] if len(unique) == 1 else "mixed"

    critical = [{"phase": d["phase"], "component": d["component"], "message": d["message"]}
                for d in degradations if d.get("severity") == "critical"]
    return {"rows": rows, "hypothesis_summary": summary, "critical_degradations": critical}
