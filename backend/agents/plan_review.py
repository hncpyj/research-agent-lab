"""
Stage S9 — review against the plan.

Checks the finished study against its own documents rather than against
generic ML conventions (the previous review counted country-year rows as a
test set, judged statistical rigour by whether the code contained "std", and
compared a yearly slope with an R² from a paper):
- every selected hypothesis has planned tests or is recorded as untestable
- every planned test has a results row, and every results row is reported
  (as a claim, in the results section, or as a limitation)
- the report's limitations include every untestable item and critical pipeline problem
- claims report the number of countries behind them
- rejected claims are listed, not silently dropped
An optional model reading may add issues; each must cite a document id
(H, T, R or C number) that exists, or it is discarded.
"""

from __future__ import annotations

import re

from router import TaskType

_JUDGE_PROMPT = """\
You are reviewing a finished study. Research question: {question}

Results table:
{table}

Claims in the report:
{claims}

List problems a careful reviewer would raise: a claim that overstates its row, a result that
does not answer the research question, or an important limitation. Each problem must name the
row or claim it is about. Use exactly one line per problem:
ISSUE: <R or C id> | <problem>
If there are none, write: ISSUE: none"""


def review(hypotheses: dict, plan: dict, table: dict, claims: dict, report: dict) -> list[dict]:
    findings = []

    def add(level, check, detail):
        findings.append({"level": level, "check": check, "detail": detail})

    planned = {t["hypothesis"] for t in plan["tests"]}
    for hid in hypotheses.get("selected", []):
        if hid not in planned:
            add("fail", "plan_coverage", f"{hid} was selected but has no planned test")

    row_tests = {r["test"] for r in table["rows"] if r["test"]}
    for t in plan["tests"]:
        if t["id"] not in row_tests:
            add("fail", "results_coverage", f"{t['id']} has no results row")

    results_text = report.get("results", "")
    limitations_text = report.get("limitations", "")
    for r in table["rows"]:
        if r["id"] not in results_text and r["compares"] not in limitations_text:
            add("warn", "unreported_result", f"{r['id']} ({r['test'] or r['hypothesis']}) appears nowhere in the report")
        if r["verdict"] == "untestable" and r["compares"] not in limitations_text:
            add("fail", "limitations", f"untestable item {r['id']} is missing from the limitations")
    for d in table["critical_degradations"]:
        if d["message"] not in limitations_text:
            add("fail", "limitations", f"critical pipeline problem not in limitations: {d['component']}")

    # Citations must point at a paper that is actually listed (2026-09-20: the
    # reference list was renumbered, so every citation named a different paper).
    keys = {str(r.get("key", "")).strip() for r in report.get("references", [])}
    cited = set()
    for section in ("introduction", "related_work", "methodology", "results", "discussion", "conclusion"):
        cited |= set(re.findall(r"\[\d+\]", report.get(section, "")))
    missing = sorted(cited - keys)
    if missing:
        add("fail", "citations", f"cited but not in the reference list: {', '.join(missing)}")

    rows = {r["id"]: r for r in table["rows"]}
    for c in claims["accepted"]:
        ns = [rows[e]["values"].get(k) for e in c["evidence"] if e in rows
              for k in ("n_units", "n_series", "n_first") if rows[e]["values"].get(k) is not None]
        if ns and not any(str(int(n)) in c["text"] for n in ns):
            add("warn", "sample_size", f"{c['id']} does not state how many countries it rests on")
    if claims["rejected"]:
        add("info", "rejected_claims", f"{len(claims['rejected'])} drafted claim(s) failed the checks and were "
                                       "left out: " + " | ".join(f"{c['text']} ({'; '.join(c['problems'])})"
                                                                  for c in claims["rejected"][:5]))
    if not findings:
        add("pass", "plan_consistency", "The report follows the approved plan and reports every result row.")
    return findings


def model_issues(api_model, question: str, table_text: str, claims: dict, valid_ids: set[str], deg=None) -> list[dict]:
    claims_text = "\n".join(f"{c['id']}: {c['text']}" for c in claims["accepted"]) or "(none)"
    try:
        raw = api_model.generate(prompt=_JUDGE_PROMPT.format(question=question, table=table_text, claims=claims_text),
                                 system="You are a careful, fair reviewer.", task_type=TaskType.NOVELTY_CHECK,
                                 max_tokens=600, temperature=0.2)
    except Exception as exc:
        if deg:
            deg.record(7, "review_model", "warn", f"Model review did not run ({exc}); code checks only.")
        return []
    issues = []
    for line in raw.splitlines():
        m = re.match(r"\W*ISSUE\s*:\s*([RC]\d+)\s*\|\s*(.+)", line.strip(), re.I)
        if m and m.group(1).upper() in valid_ids:
            issues.append({"level": "warn", "check": "model_review", "detail": f"{m.group(1).upper()}: {m.group(2).strip()}"})
    return issues
