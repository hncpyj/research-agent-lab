"""
Stage S8 — claims first, then the report.

The model first lists claims, each citing rows of the results table (S7).
Every claim is checked mechanically:
- it cites rows that exist
- every number in it is a value of a cited row (or a setting of that test),
  within the rounding the claim itself uses
- it does not call a rejected, undetermined or untestable result support
- it uses no causal language (every analysis block is observational)
Only accepted claims reach the report. Methods, results tables and limitations
are written by code from the plan, results and data audit; the model writes
the abstract, discussion and conclusion from accepted claims, and those
sections get the same number and wording checks. A section that fails twice is
replaced by the accepted claims themselves.

Background (2026-09-13, session c5a020c3): the report concluded that stricter
energy policy raises clean fuel use (not measurable in the data), that urban
areas rose faster (the opposite held in the full sample), and that results
were robust to sensitivity analyses (none were run).
"""

from __future__ import annotations

import re

from router import TaskType
from tools.analysis_blocks import BLOCKS

# Verbs and phrases that assert causation. "causal"/"causation" are not listed: they
# appear in the required disclaimer ("none supports a causal conclusion"), which a
# 2026-09-14 check rejected.
CAUSAL = re.compile(r"\b(causes?|caused|causing|effects? of|impacts? of|leads? to|led to|drives?|driven by|due to|"
                    r"because of|results? in|resulted in|thanks to|attributable to the)\b", re.I)
SUPPORT_WORDS = re.compile(r"(?<!not )(?<!no )(?<!n't )\b(supports?|confirms?|demonstrates?|proves?|shows? that|"
                           r"establish\w*)\b", re.I)
_ID_TOKENS = re.compile(r"\b(?:H\d+(?:\.T\d+)?|R\d+|C\d+|SDG\s?\d+(?:\.\d+)*)\b")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?%?")

_SYSTEM = "You write precise scientific claims. You never state anything the results table does not show."

_CLAIM_PROMPT = """\
Research question: {question}

RESULTS TABLE (final; each row's verdict comes from a rule fixed before the analysis ran):
{table}

Write 2 to 6 claims that answer the research question from these rows. Rules:
- Use only numbers that appear in the cited row (you may round them).
- State how many countries the claim rests on, using the n value in its row.
- A row whose verdict is rejected, undetermined or untestable must be described as such.
- These analyses are observational: never say one thing causes, drives, affects or leads to another.
Use exactly this format:
CLAIM: C1
TEXT: <one sentence>
EVIDENCE: R1
{feedback}"""

_SECTION_PROMPT = """\
Research question: {question}

ACCEPTED CLAIMS (the only findings you may state):
{claims}

LIMITATIONS:
{limitations}

Write the {section} of a research report in {length}. Use only the claims above and their numbers.
Do not add numbers, findings or citations that are not listed. The analyses are observational:
never say one thing causes, drives, affects or leads to another.
{coverage}Output only the text.
{feedback}"""


def format_table(table: dict) -> str:
    lines = []
    for r in table["rows"]:
        values = ", ".join(f"{k}={_fmt(v)}" for k, v in r["values"].items())
        lines.append(f"{r['id']} | {r['test'] or r['hypothesis']} | verdict {r['verdict']} | {r['compares']}"
                     + (f" | {values}" if values else "") + f" | why: {r['reason']}")
    return "\n".join(lines)


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def parse_claims(raw: str) -> list[dict]:
    claims, current = [], None
    for line in raw.splitlines():
        line = re.sub(r"[*`]+", "", line).strip().lstrip("-• ").strip()
        m = re.match(r"CLAIM\s*:\s*(C\d+)", line, re.I)
        if m:
            current = {"id": m.group(1).upper(), "text": "", "evidence": []}
            claims.append(current)
        elif current is not None and re.match(r"TEXT\s*:", line, re.I):
            current["text"] = line.split(":", 1)[1].strip()
        elif current is not None and re.match(r"EVIDENCE\s*:", line, re.I):
            current["evidence"] = re.findall(r"R\d+", line.split(":", 1)[1].upper())
    return [c for c in claims if c["text"]]


def _numbers(text: str) -> list[tuple[float, int, bool]]:
    """(value, decimals, is_percent) for every number in text, ignoring ids like H2.T1 or R3."""
    out = []
    for token in _NUMBER.findall(_ID_TOKENS.sub(" ", text)):
        pct = token.endswith("%")
        core = token.rstrip("%").replace(",", "")
        decimals = len(core.split(".")[1]) if "." in core else 0
        out.append((float(core), decimals, pct))
    return out


def allowed_numbers(rows: list[dict], plan_tests: dict) -> list[float]:
    values = []
    for r in rows:
        proportion_ci = r.get("block") == "class_agreement"
        for k, v in r["values"].items():
            if isinstance(v, (int, float)):
                values.append(float(v))
                # proportions may be stated as percentages; other estimates may not be rescaled
                if k.startswith("share") or k == "disagreement_share" or (proportion_ci and k in ("ci_low", "ci_high")):
                    values.append(float(v) * 100)
        test = plan_tests.get(r.get("test"))
        if test:
            for v in test.get("typed_params", {}).values():
                if isinstance(v, (int, float)):
                    values.append(float(v))
            values += [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", f"{test['support_if']} {test['reject_if']}")]
    return values


def number_problems(text: str, allowed: list[float]) -> list[str]:
    problems = []
    for value, decimals, pct in _numbers(text):
        tolerance = 0.5 * 10 ** (-decimals) + 1e-9
        candidates = allowed if not pct else allowed
        if not any(abs(abs(value) - abs(a)) <= tolerance for a in candidates):
            problems.append(f"number {value:g}{'%' if pct else ''} is not in the cited results")
    return problems


_ROBUST = re.compile(r"\b(robust\w*|sensitivity analys\w*)\b", re.I)
_NEGATION = re.compile(r"\b(not|cannot|could not|no|unable|without|lacks?|absent)\b", re.I)
_STOP = {"between", "within", "countries", "country", "whether", "which", "their", "these", "those", "there",
         "about", "clean", "population", "proportion", "reliance", "primary", "technologies"}


def untestable_terms(table: dict) -> set[str]:
    """Distinctive words of untestable items that no tested row mentions (e.g. 'policies', 'prices')."""
    tested = " ".join(r["compares"].lower() for r in table["rows"] if r["verdict"] != "untestable")
    words = set()
    for r in table["rows"]:
        if r["verdict"] == "untestable":
            for w in re.findall(r"[a-z]{6,}", r["compares"].lower()):
                if w not in _STOP and w not in tested:
                    words.add(w)
    return words


_LOWER_BOUND = re.compile(r"\b(at least|more than|over|above|exceed(?:s|ed|ing)?|greater than|no less than)\s+"
                          r"(-?\d+(?:\.\d+)?)", re.I)
_UPPER_BOUND = re.compile(r"\b(at most|less than|under|below|no more than|up to)\s+(-?\d+(?:\.\d+)?)", re.I)
_ESTIMATE_KEYS = ("difference", "mean", "coef", "r", "disagreement_share", "mean_first", "mean_second", "median")


def bound_problems(text: str, table: dict) -> list[str]:
    """
    'at least X' where X is a point estimate whose confidence interval reaches
    below X (and 'at most X' mirrored). 2026-09-14 replay: "at least 29.63
    percentage points" for an estimate of 29.63 with CI 14.07-45.17.
    """
    problems = []
    for pattern, lower in ((_LOWER_BOUND, True), (_UPPER_BOUND, False)):
        for m in pattern.finditer(text):
            x = float(m.group(2))
            decimals = len(m.group(2).split(".")[1]) if "." in m.group(2) else 0
            tol = 0.5 * 10 ** (-decimals) + 1e-9
            for r in table["rows"]:
                v = r.get("values", {})
                lo, hi = v.get("ci_low"), v.get("ci_high")
                if lo is None or hi is None:
                    continue
                if not any(isinstance(v.get(k), (int, float)) and min(abs(v[k] - x), abs(v[k] * 100 - x)) <= tol
                           for k in _ESTIMATE_KEYS):
                    continue
                scale = 100 if not any(isinstance(v.get(k), (int, float)) and abs(v[k] - x) <= tol
                                       for k in _ESTIMATE_KEYS) else 1
                if lower and x > lo * scale + tol:
                    problems.append(f"'{m.group(0)}' overstates {r['id']}: its confidence interval starts at "
                                    f"{lo * scale:.4g}")
                if not lower and x < hi * scale - tol:
                    problems.append(f"'{m.group(0)}' understates {r['id']}: its confidence interval reaches "
                                    f"{hi * scale:.4g}")
    return problems


def wording_problems(text: str, table: dict, plan: dict) -> list[str]:
    """Checks shared by claims and model-written sections."""
    problems = bound_problems(text, table)
    if CAUSAL.search(text):
        problems.append(f"causal wording ({CAUSAL.search(text).group(0)!r}) for an observational result")
    planned_robustness = any(_ROBUST.search(t["compares"]) for t in plan["tests"])
    if _ROBUST.search(text) and not planned_robustness:
        problems.append("mentions robustness or sensitivity analyses, which the plan does not contain")
    terms = untestable_terms(table)
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        hit = next((w for w in terms if re.search(rf"\b{w}\b", sentence.lower())), None)
        if hit and not _NEGATION.search(sentence):
            problems.append(f"states something about {hit!r}, which this data cannot test")
    return problems


_NOT_SIGNIFICANT = re.compile(r"\b(?:not|no|non)[-\s]?(?:statistically\s+)?significan\w*", re.I)
_SIGNIFICANT = re.compile(r"\bsignifican\w*", re.I)
# Blocks whose estimate is a difference or an association, where "significant"
# means its confidence interval excludes zero. A share (class_agreement) has no
# such null, so the word is not checked against its interval.
_ZERO_NULL_BLOCKS = ("paired_difference", "group_comparison", "trajectory_group_comparison",
                     "panel_fe_regression", "correlation")


def significance_problem(text: str, row: dict) -> str | None:
    """
    Two accepted claims cited the same row, one calling it significant and the
    other not (2026-09-20, session c5a020c3). The row's own interval settles it.
    """
    if row.get("block") not in _ZERO_NULL_BLOCKS:
        return None
    lo, hi = row.get("values", {}).get("ci_low"), row.get("values", {}).get("ci_high")
    if lo is None or hi is None:
        return None
    excludes_zero = lo > 0 or hi < 0
    if _NOT_SIGNIFICANT.search(text):
        return (f"calls {row['id']} not significant, but its 95% interval ({lo:.4g} to {hi:.4g}) excludes zero"
                if excludes_zero else None)
    if _SIGNIFICANT.search(text) and not excludes_zero:
        return f"calls {row['id']} significant, but its 95% interval ({lo:.4g} to {hi:.4g}) includes zero"
    return None


_LOWER_WORDS = r"lower|less|slower|smaller|weaker|fell|declined|decreasing|decreased"
_HIGHER_WORDS = r"higher|greater|faster|larger|stronger|rose|rising|increased|increasing"


def direction_problem(text: str, row: dict, test: dict | None, meanings: dict) -> str | None:
    """
    "X is lower than Y" must agree with the sign of the estimate, which is the
    first group of the pair minus the second. On 2026-09-20 a claim said urban
    rose more slowly than rural in the 81 countries where the estimate was
    +0.30 — urban rising faster — and every other check passed it.
    """
    if row.get("block") not in _ZERO_NULL_BLOCKS or not meanings:
        return None
    values = row.get("values", {})
    estimate = next((values[k] for k in ("mean", "difference", "coef") if isinstance(values.get(k), (int, float))), None)
    params = (test or {}).get("typed_params", {})
    pair = params.get("pair") or params.get("pair_y")
    if estimate is None or not pair:
        return None
    codes = [c.strip() for c in pair.partition(":")[2].split(",")]
    words = [meanings.get(c, "").strip().lower() for c in codes]
    if len(words) != 2 or not all(words) or words[0] == words[1]:
        return None
    # "urban is lower than rural" and "lower in urban areas than in rural areas"
    # both occur, so the comparative may sit on either side of the subject.
    side = rf"\b({re.escape(words[0])}|{re.escape(words[1])})\b"
    comparatives = rf"\b({_LOWER_WORDS}|{_HIGHER_WORDS})\b"
    low = text.lower()
    subject = comparative = other = None
    for m_than in re.finditer(r"\bthan\b", low):
        before = low[low.rfind(".", 0, m_than.start()) + 1:m_than.start()]
        rest = low[m_than.end():]
        after = rest[:rest.find(".") if "." in rest else len(rest)]
        subjects = re.findall(side, before)
        comps = re.findall(comparatives, before)
        others = re.findall(side, after)
        if subjects and comps and others:
            subject, comparative, other = subjects[-1], comps[-1], others[0]
            break
    if not subject or subject == other:
        return None
    says_higher = bool(re.fullmatch(_HIGHER_WORDS, comparative))
    expect_positive = says_higher == (subject == words[0])
    if (estimate > 0) != expect_positive:
        return (f"says {subject} is {comparative} than {other}, but {row['id']} is {estimate:+.4g} "
                f"({words[0]} minus {words[1]})")
    return None


def uncited_decided_rows(accepted: list[dict], table: dict) -> list[dict]:
    """Decided results no claim mentions — the reader's summary would omit them."""
    covered = {e for c in accepted for e in c["evidence"]}
    return [r for r in table["rows"] if r["verdict"] in ("supported", "rejected") and r["id"] not in covered]


def claim_for_row(row: dict) -> dict:
    """
    A claim written from the row itself, for a decided result the model left
    out. It states the estimate with its sign: a first version said only "the
    pre-registered rule was supported", and the abstract then described a
    reversed difference (-0.15 overall, +0.30 restricted) as unchanged.
    """
    values = row.get("values", {})
    estimate = next((k for k in ("mean", "difference", "coef", "r", "disagreement_share") if k in values), None)
    counts = row_counts([row])
    parts = []
    if estimate:
        parts.append(f"{estimate} = {values[estimate]:+.4g}" if isinstance(values[estimate], (int, float))
                     else f"{estimate} = {values[estimate]}")
    if values.get("ci_low") is not None and values.get("ci_high") is not None:
        parts.append(f"95% CI {_fmt(values['ci_low'])} to {_fmt(values['ci_high'])}")
    if counts:
        parts.append(f"n = {' and '.join(str(n) for n in counts)} countries")
    verdict = "supported" if row["verdict"] == "supported" else "rejected"
    compares = f"{row['compares'][0].lower()}{row['compares'][1:]}"
    return {"id": "", "text": f"For {compares}, the estimate is {'; '.join(parts)}, which {verdict} "
                              "the rule fixed before the analysis.",
            "evidence": [row["id"]], "problems": [], "generated": True}


def claim_problems(claim: dict, rows_by_id: dict, plan_tests: dict, table: dict | None = None,
                   plan: dict | None = None, meanings: dict | None = None) -> list[str]:
    problems = []
    cited = [rows_by_id[e] for e in claim["evidence"] if e in rows_by_id]
    if not claim["evidence"]:
        return ["cites no results row"]
    if len(cited) != len(claim["evidence"]):
        problems.append("cites a results row that does not exist")
    if not cited:
        return problems
    problems += number_problems(claim["text"], allowed_numbers(cited, plan_tests))
    if table is not None and plan is not None:
        problems += wording_problems(claim["text"], table, plan)
    elif CAUSAL.search(claim["text"]):
        problems.append(f"causal wording ({CAUSAL.search(claim['text']).group(0)!r}) for an observational result")
    if SUPPORT_WORDS.search(claim["text"]) and any(r["verdict"] != "supported" for r in cited):
        problems.append("describes a result that is not 'supported' as supporting or confirming")
    if any(r["verdict"] == "untestable" for r in cited) and not _NEGATION.search(claim["text"]):
        problems.append("presents an untestable item as a finding")
    if counts_missing(claim["text"], cited):
        problems.append(MISSING_COUNTS)
    problems += [p for p in (significance_problem(claim["text"], r) for r in cited) if p]
    problems += [p for p in (direction_problem(claim["text"], r, plan_tests.get(r.get("test")), meanings or {})
                             for r in cited) if p]
    return problems


MISSING_COUNTS = "does not state how many countries it rests on"


def row_counts(rows: list[dict]) -> list[int]:
    return [int(v) for r in rows for k, v in r.get("values", {}).items()
            if k in ("n_units", "n_series", "n_first", "n_second") and isinstance(v, (int, float))]


def counts_missing(text: str, rows: list[dict]) -> bool:
    counts = row_counts(rows)
    return bool(counts) and not any(str(n) in text for n in counts)


def with_counts(text: str, rows: list[dict]) -> str:
    """
    Append the number of countries when the claim does not give it. The 8b model
    leaves it out of nearly every claim (2026-09-20: 9 of 9), and rejecting them
    dropped the study's only supported finding from the report.
    """
    counts = row_counts(rows)
    if not counts or not counts_missing(text, rows):
        return text
    return f"{text.rstrip('.')} (n = {' and '.join(str(n) for n in counts)} countries)."


_INSTRUCTION = re.compile(r"\b(you|your|yours|treat (?:both|this|that|these)|rely on|do not|don't|make sure|"
                          r"say so|record the|use the|note that you)\b", re.I)
_INTERNAL_ID = re.compile(r"\s*[\(\[](?:(?:C|R)\d+|H\d+(?:\.T\d+)?)(?:\s*,\s*(?:(?:C|R)\d+|H\d+(?:\.T\d+)?))*[\)\]]")
_COVERAGE = re.compile(r"\b(could not|cannot|can not|not testable|undetermined|unable to|no variable|"
                       r"does not (?:contain|include|have)|remains? (?:open|unanswered))\b", re.I)


def brief_background(text: str) -> str:
    """
    The brief with its instructions to the agent removed. The first report to
    reach a reader printed "Treat both of those as claims to verify…" and
    "One warning about your own paper collection…" in its introduction.
    """
    kept = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip())
            if s.strip() and not _INSTRUCTION.search(s)]
    return " ".join(kept)


def clean_gap_report(text: str) -> str:
    """
    The gap report as related work: sections the model marked NOT_APPLICABLE are
    dropped (one said there were no disagreements directly under two of them),
    and the collection-health paragraph is left to the limitations section.
    """
    from agents.gap_analysis import _is_section_heading

    out, skipping = [], False
    for line in (text or "").splitlines():
        stripped = re.sub(r"[*#`]+", "", line).strip()
        if _is_section_heading(line):
            skipping = "NOT_APPLICABLE" in line or stripped.upper().startswith("COLLECTION HEALTH")
        elif stripped.upper().startswith("COLLECTION HEALTH"):
            skipping = True
        elif "NOT_APPLICABLE" in line:
            skipping = True
            continue
        if not skipping:
            out.append(line)
    return "\n".join(out).strip()


def unanswered(table: dict) -> tuple[list[str], list[str]]:
    """(question parts with no variable, planned tests that stayed undecided)."""
    return ([r["compares"] for r in table["rows"] if r["verdict"] == "untestable"],
            [r["test"] for r in table["rows"] if r["verdict"] == "undetermined"])


def coverage_sentence(table: dict) -> str:
    untestable, undecided = unanswered(table)
    parts = []
    if untestable:
        parts.append("this data has no variable for " + "; ".join(untestable))
    if undecided:
        parts.append(f"{', '.join(undecided)} stayed undecided under the rules fixed before the analysis")
    return ("The research question is only partly answered: " + "; and ".join(parts) + ".") if parts else ""


def limitations(table: dict, plan: dict, audit: dict) -> list[str]:
    items = []
    for r in table["rows"]:
        if r["verdict"] == "untestable":
            items.append(f"Not testable with this data ({r['hypothesis']}): {r['compares']} — {r['reason']}.")
        elif r["verdict"] == "undetermined":
            items.append(f"{r['test']} could not be decided: {r['reason']}.")
        for note in r.get("notes", []):
            items.append(f"{r.get('test') or r['hypothesis']}: {note}.")
    for t in plan["tests"]:
        if t.get("threats"):
            items.append(f"{t['id']} threats named in the plan: {t['threats']}")
    # data limits about indicators this study did not use are not its limitations
    used = {v for t in plan["tests"] for k, v in t.get("typed_params", {}).items()
            if k.startswith("indicator") and isinstance(v, str)}
    all_codes = {i["code"] for i in audit.get("indicators", [])}
    for limit in audit.get("limits", []):
        named = {c for c in all_codes if re.search(rf"\b{re.escape(c)}\b", limit)}
        if not named or named & used:
            items.append(limit)
    items += [f"Pipeline problem recorded ({d['component']}): {d['message']}" for d in table["critical_degradations"]]
    items.append("All analyses are observational country-level comparisons; none supports a causal conclusion.")
    return items


def provenance_line(provenance: dict | None) -> str:
    """Which run produced this report. The rendered date is only the day it was downloaded."""
    if not provenance:
        return ""
    bits = [f"Session {provenance.get('session_id', '?')}",
            f"analysis code {str(provenance.get('code_hash', '?'))[:12]}",
            f"analysis run {provenance.get('run_at', '?')}",
            f"plan version {provenance.get('plan_version', '?')}"]
    return "Provenance: " + "; ".join(bits) + ".\n\n"


def methodology(audit: dict, hypotheses: dict, plan: dict) -> str:
    indicators = {i["code"]: i for i in audit["indicators"]}
    used = sorted({v for t in plan["tests"] for k, v in t["typed_params"].items()
                   if k.startswith("indicator") and isinstance(v, str)})
    parts = [f"Data: {audit['source']}. Country-level rows only."]
    for code in used:
        ind = indicators.get(code, {})
        parts.append(f"- {code}: {ind.get('meaning', code)} (unit {ind.get('unit', '?')}; "
                     f"{ind.get('n_countries', '?')} countries; {ind.get('years', ['?', '?'])[0]}-{ind.get('years', ['?', '?'])[1]})")
    selected = set(hypotheses.get("selected", []))
    for h in hypotheses.get("hypotheses", []):
        if h["id"] in selected:
            rows = "; ".join(f"{r['concept']} = {r['variable']}" + (f" ({r['split']})" if r.get("split") else "")
                             for r in h["rows"])
            parts.append(f"\nHypothesis {h['id']}: {h['statement']}\nOperationalization: {rows}")
    parts.append("\nAnalysis plan (fixed and approved before the analysis ran):")
    for t in plan["tests"]:
        spec = BLOCKS[t["block"]]
        params = ", ".join(f"{k}={v}" for k, v in t["typed_params"].items())
        parts.append(f"- {t['id']}: {t['compares']} Method: {spec.summary} ({t['block']}; {params}). "
                     f"Supported if {t['support_if']}; rejected if {t['reject_if']}.")
    return "\n".join(parts)


def results_text(table: dict, accepted: list[dict]) -> str:
    lines = ["Results by planned test (verdicts apply the pre-registered rules):"]
    for r in table["rows"]:
        values = ", ".join(f"{k} = {_fmt(v)}" for k, v in r["values"].items())
        lines.append(f"- {r['id']} {r['test'] or r['hypothesis']} [{r['verdict']}]: {r['compares']}"
                     + (f" ({values}; source {r['source']})" if values else f" ({r['reason']})"))
    if accepted:
        lines.append("\nFindings:")
        lines += [f"- {c['text']} [{', '.join(c['evidence'])}]" for c in accepted]
    return "\n".join(lines)


class ClaimsReportWriter:
    def __init__(self, api_model, deg=None) -> None:
        self._api = api_model
        self._deg = deg

    def claims(self, question: str, table: dict, plan: dict, meanings: dict | None = None) -> dict:
        rows_by_id = {r["id"]: r for r in table["rows"]}
        plan_tests = {t["id"]: t for t in plan["tests"]}
        feedback, attempts = "", []
        for _ in range(2):
            raw = self._api.generate(prompt=_CLAIM_PROMPT.format(question=question, table=format_table(table),
                                                                 feedback=feedback),
                                     system=_SYSTEM, task_type=TaskType.PAPER_WRITING, max_tokens=900,
                                     temperature=0.2)
            parsed = parse_claims(raw)
            for c in parsed:
                cited = [rows_by_id[e] for e in c["evidence"] if e in rows_by_id]
                c["text"] = with_counts(c["text"], cited)
                c["problems"] = claim_problems(c, rows_by_id, plan_tests, table, plan, meanings)
            attempts.append(parsed)
            bad = [f"{c['id']}: {p}" for c in parsed for p in c["problems"]]
            missing = uncited_decided_rows([c for c in parsed if not c["problems"]], table)
            if parsed and not bad and not missing:
                break
            notes = list(bad)
            notes += [f"no claim mentions {r['id']} ({r['verdict']}): {r['compares']}" for r in missing]
            feedback = ("\nFix these and reply with the full list of claims again:\n- " + "\n- ".join(notes)
                        if notes else "\nYour reply had no CLAIM/TEXT/EVIDENCE lines. Use the format exactly.")
        # Accepted claims come from one attempt (the last with any), so a rewrite
        # does not sit next to near-duplicates from the first draft; every
        # rejected draft is kept for the record.
        accepted = next(([c for c in parsed if not c["problems"]] for parsed in reversed(attempts)
                         if any(not c["problems"] for c in parsed)), [])
        rejected = [c for parsed in attempts for c in parsed if c["problems"]]
        # A decided result the model still left out is written from the row, so
        # the summary cannot omit the study's own findings.
        for row in uncited_decided_rows(accepted, table):
            accepted.append(claim_for_row(row))
            if self._deg:
                self._deg.record(7, "claims", "warn",
                                 f"No model-written claim mentioned {row['id']} ({row['verdict']}); "
                                 "a claim was written from the results row instead.")
        for i, c in enumerate(accepted, 1):
            c["id"] = f"C{i}"
        if not accepted and self._deg:
            self._deg.record(7, "claims", "critical", "No claim passed the checks; the report states results "
                                                      "only as the results table.")
        return {"accepted": accepted, "rejected": rejected}

    def _section(self, section: str, length: str, question: str, accepted: list[dict], limits: list[str],
                 allowed: list[float], table: dict, plan: dict, require_coverage: bool = False) -> tuple[str, list[str]]:
        claims_text = "\n".join(f"{c['id']}: {c['text']}" for c in accepted) or "(no accepted claims)"
        shown_limits = limits[:12]
        allowed = allowed + [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", " ".join(shown_limits))]
        coverage = coverage_sentence(table)
        instruction = (f"Say plainly what the study could not answer: {coverage}\n"
                       if require_coverage and coverage else "")
        feedback = ""
        for _ in range(2):
            text = self._api.generate(
                prompt=_SECTION_PROMPT.format(question=question, claims=claims_text,
                                              limitations="\n".join(f"- {l}" for l in shown_limits),
                                              section=section, length=length, coverage=instruction,
                                              feedback=feedback),
                system=_SYSTEM, task_type=TaskType.PAPER_WRITING, max_tokens=700, temperature=0.3).strip()
            problems = number_problems(text, allowed) + wording_problems(text, table, plan)
            if re.search(r"\[\d+\]", text):
                problems.append("cites papers although no citations were provided")
            # An abstract or conclusion that never says what the study could not
            # answer reads as if the research question was answered (2026-09-20).
            if instruction and not _COVERAGE.search(text):
                problems.append("does not say which part of the research question went unanswered")
            elif instruction:
                # Saying "undetermined" about the tests is not enough when the data
                # could not measure part of the question at all.
                terms = untestable_terms(table)
                if terms and not any(re.search(rf"\b{t}\b", text.lower()) for t in terms):
                    problems.append("does not mention what the data cannot measure at all "
                                    f"({', '.join(sorted(terms)[:4])})")
            if not problems:
                return _INTERNAL_ID.sub("", text), []
            feedback = "\nYour previous text had problems; rewrite it without them:\n- " + "\n- ".join(problems)
        fallback = "\n".join(f"- {c['text']}" for c in accepted) or "No finding passed the checks."
        if instruction:
            fallback += f"\n\n{coverage}"
        if self._deg:
            self._deg.record(7, "report", "warn", f"The {section} failed its checks twice ({'; '.join(problems)}); "
                                                   "replaced by the accepted claims.")
        return fallback, problems

    def report(self, session: dict, audit: dict, hypotheses: dict, plan: dict, table: dict, claims: dict,
               papers: list[dict], provenance: dict | None = None) -> dict:
        question = session.get("research_question") or ""
        accepted = claims["accepted"]
        limits = limitations(table, plan, audit)
        rows_by_id = {r["id"]: r for r in table["rows"]}
        plan_tests = {t["id"]: t for t in plan["tests"]}
        cited_rows = [rows_by_id[e] for c in accepted for e in c["evidence"] if e in rows_by_id]
        allowed = allowed_numbers(cited_rows, plan_tests)

        abstract, _ = self._section("abstract", "120 to 180 words", question, accepted, limits, allowed, table, plan,
                                    require_coverage=True)
        discussion, _ = self._section("discussion", "150 to 250 words", question, accepted, limits, allowed, table, plan)
        conclusion, _ = self._section("conclusion", "60 to 100 words", question, accepted, limits, allowed, table, plan,
                                      require_coverage=True)

        gap = (session.get("gap_report") or "").split("\n## Automated report checks")[0].split("\n## Gap Validation")[0]
        cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", gap) if 1 <= int(n) <= len(papers)})
        return {
            "title": question or session.get("topic") or "Research Report",
            "abstract": abstract,
            "introduction": (f"Research question: {question}\n\n"
                             f"Background (from the research brief): {brief_background(session.get('background')) or 'Not given.'}"),
            "related_work": clean_gap_report(gap) or "Not available.",
            "methodology": (provenance_line(provenance) + methodology(audit, hypotheses, plan)),
            "results": results_text(table, accepted),
            "discussion": discussion,
            "limitations": "\n".join(f"- {l}" for l in limits),
            "conclusion": conclusion,
            "references": [{"key": f"[{n}]", "title": str(papers[n - 1].get("title") or ""),
                            "authors": str(papers[n - 1].get("authors") or ""),
                            "venue": str(papers[n - 1].get("source") or ""),
                            "year": str(papers[n - 1].get("year") or "")}
                           for n in cited],
        }
