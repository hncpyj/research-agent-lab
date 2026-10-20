"""
Stage S4 — analysis plan, fixed before any result exists.

For each selected hypothesis the model picks blocks from the analysis menu
(tools/analysis_blocks.py), fills their parameters, and writes the decision
rule: which block outputs mean the hypothesis is supported, and which mean it
is rejected. Everything is checked here; the user then approves the plan, and
may edit its text first.

Checks:
- the block exists; parameters are known, required ones present, values typed
- indicators, splits and groups come from the hypothesis' own
  operationalization rows (S3), and splits belong to that indicator
- saturation-style cut-offs are only allowed on percentage indicators
- rules use only the block's outputs, and SUPPORT_IF and REJECT_IF cannot both
  be true (checked exhaustively over the rules' threshold regions)
"""

from __future__ import annotations

import itertools
import re

from router import TaskType
from tools.analysis_blocks import BLOCKS, CLASSES, describe_menu, with_defaults

_PERCENT_ONLY = {"saturation", "exclude_at_or_above"}
_RULE_TERM = re.compile(r"^\s*([a-z_]+)\s*(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")

_SYSTEM = ("You are a careful statistician writing a pre-registered analysis plan. You use only the "
           "analysis blocks and variables you are given.")

_PROMPT = """\
Hypothesis {hid}: {statement}

Variables this hypothesis may use:
{variables}

Analysis blocks you may use (params ending in ? are optional):
{menu}

Allowed parameter values for this hypothesis (copy them exactly; nothing else is valid):
{allowed}
- saturation and exclude_at_or_above: only for indicators whose unit is %
- numbers in SUPPORT_IF and REJECT_IF must be numbers, never another output name

Write 1 to 3 tests that would support or reject this hypothesis. Each test is one block
run on the variables above. Groups of countries are either a country group listed above, or
trajectory classes (rising, stalled, reversed, saturated, not_rising) formed with the block
trajectory_group_comparison. Use exactly this format:
TEST: {hid}.T1
COMPARES: <one sentence: what is compared>
BLOCK: <block name>
PARAMS: name=value; name=value
SUPPORT_IF: <output> <op> <number> AND <output> <op> <number>
REJECT_IF: <output> <op> <number>
THREATS: <what could make the result misleading>

Example of the format with this hypothesis' variables:
{example}
{feedback}"""


# --- variables ----------------------------------------------------------------

def hypothesis_variables(hypothesis: dict, audit: dict) -> dict:
    """What a plan for this hypothesis may reference, from its checked rows."""
    indicators = {i["code"]: i for i in audit["indicators"]}
    meanings = {s["code"]: s["meaning"] for i in audit["indicators"] for c in i["splits"].values() for s in c}
    meanings.update({g["code"]: g["meaning"] for c in audit["groups"].values() for g in c})
    out = {"indicators": {}, "splits": {}, "groups": {}, "meanings": meanings}
    for row in hypothesis["rows"]:
        if row.get("problem"):
            continue
        variable = row["variable"].strip()
        if row.get("kind") == "indicator":
            out["indicators"][variable] = indicators[variable]
            if row.get("split"):
                col, _, codes = row["split"].partition(":")
                out["splits"].setdefault(col, set()).update(codes.split(","))
        elif row.get("kind") in ("split", "group"):
            col, _, codes = variable.partition(":")
            key = "splits" if row["kind"] == "split" else "groups"
            out[key].setdefault(col.strip(), set()).update(c.strip() for c in codes.split(",") if c.strip())
    return out


def allowed_values(variables: dict) -> str:
    lines = [f"- indicator / indicator_x / indicator_y: {code}" for code in variables["indicators"]]
    for col, codes in variables["splits"].items():
        codes = sorted(codes)
        for a, b in itertools.permutations(codes, 2):
            lines.append(f"- pair: {col}:{a},{b}")
        for c in codes:
            lines.append(f"- slice / slice_x / slice_y / split: {col}:{c}")
    for col, codes in variables["groups"].items():
        for a, b in itertools.permutations(sorted(codes), 2):
            lines.append(f"- groups: {col}:{a},{b}")
    return "\n".join(lines)


def example_test(hid: str, variables: dict) -> str:
    indicator = next(iter(variables["indicators"]), "INDICATOR")
    pair = next(((col, sorted(codes)) for col, codes in variables["splits"].items() if len(codes) >= 2), None)
    if pair:
        col, (a, b) = pair[0], pair[1][:2]
        lines = [f"TEST: {hid}.T1", f"COMPARES: within-country difference in yearly trend between {a} and {b}",
                 "BLOCK: paired_difference", f"PARAMS: indicator={indicator}; pair={col}:{a},{b}; stat=slope",
                 "SUPPORT_IF: mean > 0 AND ci_low > 0", "REJECT_IF: ci_high < 0", "THREATS: <threats>"]
    else:
        lines = [f"TEST: {hid}.T1", "COMPARES: how many countries show a rising trend", "BLOCK: series_trend",
                 f"PARAMS: indicator={indicator}", "SUPPORT_IF: share_rising_ci > 0.5",
                 "REJECT_IF: share_rising_ci <= 0.5", "THREATS: <threats>"]
    return "\n".join(lines)


def describe_variables(variables: dict, audit: dict) -> str:
    lines = []
    for code, ind in variables["indicators"].items():
        lines.append(f"- indicator {code}: {ind['meaning']} [unit {ind['unit']}]")
    meanings = {s["code"]: s["meaning"] for i in audit["indicators"] for c in i["splits"].values() for s in c}
    meanings.update({g["code"]: g["meaning"] for c in audit["groups"].values() for g in c})
    for kind in ("splits", "groups"):
        for col, codes in variables[kind].items():
            lines.append(f"- {kind[:-1]} {col}: " + ", ".join(f"{c} ({meanings.get(c, c)})" for c in sorted(codes)))
    return "\n".join(lines)


# --- parsing ------------------------------------------------------------------

def parse_plan(text: str) -> list[dict]:
    tests, current = [], None
    for line in text.splitlines():
        line = re.sub(r"[*`]+", "", line).strip().lstrip("-• ").strip()
        m = re.match(r"TEST\s*:\s*(H\d+\.T\d+)", line, re.I)
        if m:
            current = {"id": m.group(1).upper(), "compares": "", "block": "", "params": {}, "support_if": "",
                       "reject_if": "", "threats": ""}
            tests.append(current)
            continue
        if current is None or ":" not in line:
            continue
        label, value = (part.strip() for part in line.split(":", 1))
        label = label.upper()
        if label == "COMPARES":
            current["compares"] = value
        elif label == "BLOCK":
            current["block"] = value.strip()
        elif label == "PARAMS":
            # the 8b model separates parameters with commas as often as semicolons
            for part in re.split(r";|,(?=\s*[A-Za-z_]+\s*=)", value):
                key, sep, val = part.partition("=")
                if sep and key.strip():
                    current["params"][key.strip()] = val.strip()
        elif label == "SUPPORT_IF":
            current["support_if"] = value
        elif label == "REJECT_IF":
            current["reject_if"] = value
        elif label == "THREATS":
            current["threats"] = value
    for t in tests:
        t["hypothesis"] = t["id"].split(".")[0]
    return tests


def parse_rule(rule: str) -> tuple[str, list[tuple[str, str, float]]]:
    """'a > 0 AND b < 1' -> ('AND', [('a','>',0.0), ('b','<',1.0)]). Raises ValueError."""
    if not rule.strip():
        raise ValueError("empty rule")
    upper = f" {rule} ".upper()
    if " AND " in upper and " OR " in upper:
        raise ValueError("mixes AND and OR")
    joiner = "OR" if " OR " in upper else "AND"
    terms = []
    for part in re.split(rf"\s+{joiner}\s+", rule.strip(), flags=re.I):
        m = _RULE_TERM.match(part)
        if not m:
            raise ValueError(f"cannot read condition {part!r}")
        terms.append((m.group(1), m.group(2), float(m.group(3))))
    return joiner, terms


def evaluate_rule(rule: str, values: dict) -> bool | None:
    """True/False, or None when an output the rule needs is missing."""
    joiner, terms = parse_rule(rule)
    results = []
    for key, op, num in terms:
        v = values.get(key)
        if v is None:
            return None
        results.append({">": v > num, ">=": v >= num, "<": v < num, "<=": v <= num}[op])
    return all(results) if joiner == "AND" else any(results)


_ESTIMATES = ("mean", "difference", "coef", "r", "disagreement_share")


def _possible(values: dict) -> bool:
    """Whether block outputs could take these values together: CI bounds bracket the estimate, shares and p in [0, 1]."""
    lo, hi = values.get("ci_low"), values.get("ci_high")
    if lo is not None and hi is not None and lo > hi:
        return False
    for key in _ESTIMATES:
        v = values.get(key)
        if v is not None and ((lo is not None and v < lo) or (hi is not None and v > hi)):
            return False
    for key, v in values.items():
        if (key.startswith("share") or key.endswith("_p") or key in ("p", "disagreement_share")) and not 0 <= v <= 1:
            return False
        if key == "r" and not -1 <= v <= 1:
            return False
    return True


def _both_can_hold(support: str, reject: str) -> dict | None:
    """An assignment of outputs making both rules true, or None. Exact for threshold rules."""
    terms = parse_rule(support)[1] + parse_rule(reject)[1]
    points: dict[str, set[float]] = {}
    for key, _, num in terms:
        points.setdefault(key, set()).update({num - 1e-6, num, num + 1e-6})
    keys = sorted(points)
    for key in keys:
        points[key].update({min(points[key]) - 1, max(points[key]) + 1})
    grids = [sorted(points[k]) for k in keys]
    for combo in itertools.islice(itertools.product(*grids), 200_000):
        values = dict(zip(keys, combo))
        if not _possible(values):
            continue
        if evaluate_rule(support, values) and evaluate_rule(reject, values):
            return {k: round(v, 6) for k, v in values.items()}
    return None


# --- validation ---------------------------------------------------------------

def _resolve_selector(raw: str, pool: dict[str, set[str]], meanings: dict[str, str]) -> tuple[str, list[str]]:
    """
    'Column:CODE,CODE', or plain names such as 'urban,rural' that equal exactly
    one code's meaning within one column of the pool (the 8b model writes names).
    Anything ambiguous is returned unresolved and fails validation.
    """
    col, sep, codes_text = raw.partition(":")
    if sep:
        return col.strip(), [c.strip() for c in codes_text.split(",") if c.strip()]
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    for column, codes in pool.items():
        by_meaning = {}
        for code in codes:
            by_meaning.setdefault(meanings.get(code, "").strip().lower(), []).append(code)
        resolved = [by_meaning.get(n, []) for n in names]
        if names and all(len(r) == 1 for r in resolved):
            return column, [r[0] for r in resolved]
    return "", []


def _codes_of(indicator: dict, col: str) -> set[str]:
    return {s["code"] for s in indicator["splits"].get(col, [])}


_CLASSIFYING = ("trajectory_class", "class_agreement", "trajectory_group_comparison")


def auto_threats(block: str, typed: dict, indicators: dict) -> list[str]:
    """
    Weaknesses a reader must be told about, added to the test's threats instead
    of blocking the plan. From the first finished study (2026-09-20): classes
    and outcome came from the same indicator, and a percentage indicator was
    classified with no saturation cut-off, so countries already at 100% counted
    as stalled.
    """
    notes = []
    if block == "trajectory_group_comparison" and typed.get("indicator") == typed.get("indicator_y"):
        notes.append("the classes and the compared statistic come from the same indicator, so they are not "
                     "independent")
    if block in _CLASSIFYING and "saturation" not in typed:
        unit = indicators.get(typed.get("indicator", ""), {}).get("unit")
        if unit == "%":
            notes.append("no saturation cut-off: countries already near 100% are classified as stalled")
    return notes


def validate_test(test: dict, variables: dict) -> list[str]:
    problems = []
    spec = BLOCKS.get(test["block"])
    if spec is None:
        return [f"block {test['block']!r} is not in the analysis menu"]
    params = test["params"]
    for name in params:
        if spec.param(name) is None:
            problems.append(f"{spec.name} has no parameter {name!r}")
    for p in spec.params:
        if p.required and p.name not in params:
            problems.append(f"missing required parameter {p.name}")

    typed = {}
    indicators = variables["indicators"]
    for name, raw in params.items():
        p = spec.param(name)
        if p is None:
            continue
        try:
            if p.kind == "int":
                typed[name] = int(raw)
            elif p.kind == "float":
                typed[name] = float(raw)
            elif p.kind == "choice":
                if raw not in p.choices:
                    raise ValueError(f"must be one of {', '.join(p.choices)}")
                typed[name] = raw
            elif p.kind == "indicator":
                if raw not in indicators:
                    raise ValueError("not an indicator of this hypothesis")
                typed[name] = raw
            elif p.kind == "classes":
                classes = [c.strip() for c in raw.split(",") if c.strip()]
                if len(classes) != 2 or len(set(classes)) != 2 or not set(classes) <= set(CLASSES):
                    raise ValueError(f"needs two different classes from {', '.join(CLASSES)}")
                typed[name] = ",".join(classes)
            else:  # selector, pair, slice
                pool = variables["groups"] if name == "groups" else variables["splits"]
                col, codes = _resolve_selector(raw, pool, variables.get("meanings", {}))
                if col not in pool or not codes or not set(codes) <= pool[col]:
                    raise ValueError(f"{raw} is not a {'group' if name == 'groups' else 'split'} of this hypothesis")
                if p.kind == "pair" and len(codes) != 2:
                    raise ValueError("needs exactly two codes")
                if p.kind == "slice" and len(codes) != 1:
                    raise ValueError("needs exactly one code")
                typed[name] = f"{col}:{','.join(codes)}"
        except ValueError as exc:
            problems.append(f"{name}={raw}: {exc}")

    # splits must exist for the indicator they are applied to
    for name, target in (("split", "indicator"), ("pair", "indicator"), ("slice", "indicator"),
                         ("slice_x", "indicator_x"), ("slice_y", "indicator_y"), ("pair_y", "indicator_y")):
        if name in typed and typed.get(target) in indicators:
            col, _, codes = typed[name].partition(":")
            if not set(codes.split(",")) <= _codes_of(indicators[typed[target]], col):
                problems.append(f"{typed[target]} has no split {typed[name]}")
    for name in _PERCENT_ONLY & set(typed):
        ind = indicators.get(typed.get("indicator", ""))
        if ind is not None and ind["unit"] != "%":
            problems.append(f"{name} is only allowed for percentage indicators ({ind['code']} is {ind['unit']})")

    for label in ("support_if", "reject_if"):
        try:
            for key, _, _ in parse_rule(test[label])[1]:
                if key not in spec.outputs:
                    problems.append(f"{label.upper()} uses {key!r}, which {spec.name} does not output")
        except ValueError as exc:
            problems.append(f"{label.upper()}: {exc}")
    if spec.name in ("correlation", "panel_fe_regression") and typed.get("indicator_x") and typed.get("indicator_y"):
        side = lambda s: (typed.get(f"indicator_{s}"), typed.get(f"slice_{s}"), typed.get(f"stat_{s}"))
        if side("x") == side("y"):
            problems.append("x and y are the same statistic of the same indicator (correlation 1 by construction)")
    if (spec.name == "trajectory_group_comparison" and typed.get("indicator")
            and typed.get("indicator") == typed.get("indicator_y") and not typed.get("pair_y")
            and not typed.get("slice_y")):
        problems.append("the compared statistic is the same series used to form the classes (circular)")
    for note in auto_threats(spec.name, typed, indicators):
        if note not in (test.get("threats") or ""):
            test["threats"] = ((test.get("threats") or "").rstrip() + f" [automatic: {note}]").strip()
    if not problems:
        clash = _both_can_hold(test["support_if"], test["reject_if"])
        if clash:
            problems.append(f"SUPPORT_IF and REJECT_IF can both be true, e.g. {clash}")
    if not test["compares"]:
        problems.append("COMPARES is empty")

    test["typed_params"] = with_defaults(spec, typed) if not problems else typed
    return problems


def validate_plan(tests: list[dict], hypotheses: dict[str, dict], audit: dict) -> list[dict]:
    for t in tests:
        h = hypotheses.get(t["hypothesis"])
        if h is None or not h.get("testable"):
            t["problems"] = [f"{t['hypothesis']} is not a selected testable hypothesis"]
            continue
        t["problems"] = validate_test(t, hypothesis_variables(h, audit))
    return tests


def render_plan(tests: list[dict]) -> str:
    """Tests back to the editable text format."""
    blocks = []
    for t in tests:
        params = "; ".join(f"{k}={v}" for k, v in t["params"].items())
        blocks.append(f"TEST: {t['id']}\nCOMPARES: {t['compares']}\nBLOCK: {t['block']}\nPARAMS: {params}\n"
                      f"SUPPORT_IF: {t['support_if']}\nREJECT_IF: {t['reject_if']}\nTHREATS: {t['threats']}")
    return "\n\n".join(blocks)


class PlanWriter:
    def __init__(self, api_model) -> None:
        self._api = api_model

    def write(self, hypothesis: dict, audit: dict) -> list[dict]:
        """Tests for one hypothesis, validated; one retry with the problems shown to the model."""
        variables = hypothesis_variables(hypothesis, audit)
        hyps = {hypothesis["id"]: hypothesis}
        best, feedback = [], ""
        for _ in range(2):
            prompt = _PROMPT.format(hid=hypothesis["id"], statement=hypothesis["statement"],
                                    variables=describe_variables(variables, audit), menu=describe_menu(),
                                    allowed=allowed_values(variables), example=example_test(hypothesis["id"], variables),
                                    feedback=feedback)
            raw = self._api.generate(prompt=prompt, system=_SYSTEM, task_type=TaskType.EXPERIMENT_DESIGN,
                                     max_tokens=1500, temperature=0.2)
            tests = [t for t in parse_plan(raw) if t["hypothesis"] == hypothesis["id"]]
            validate_plan(tests, hyps, audit)
            if not best or sum(len(t["problems"]) for t in tests) < sum(len(t["problems"]) for t in best):
                best = tests if tests else best
            bad = [f"{t['id']}: {p}" for t in tests for p in t["problems"]]
            if tests and not bad:
                break
            feedback = ("\nYour previous plan had these problems; fix them:\n- " + "\n- ".join(bad)
                        if bad else "\nYour previous reply had no TEST blocks. Use the format exactly.")
        return best
