"""
Gap Analysis Agent (Phase 2, Steps 3 & 4)

Step 3 [API]:  Given the literature summary, identify what is missing.
Step 3.5 [API + paper sources]: Validate each claimed gap against a fresh,
    targeted search (tools/sources) before presenting it as novel. This exists because free-generated
    gap claims ("no similar comparisons are made in RL") are frequently false —
    they describe work that already exists but wasn't in the collected paper set.
    See GapValidationFinding / validate_gap_report().
Step 4 [API]: Generate 3-5 research question candidates with feasibility notes,
    grounded in the validated (not raw) gap report.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from router import TaskType

if TYPE_CHECKING:
    from models.api_model import APIModel
    from tools.arxiv_fetcher import PaperRecord
    from memory.note_db import NoteDB

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class ResearchQuestion:
    index: int
    text: str
    feasibility_notes: str = ""
    novelty_notes: str = ""
    echoes_input: bool = False
    compliance: str = "unchecked"   # "pass" | "fail" | "unchecked"
    compliance_notes: str = ""


@dataclass
class GapValidationFinding:
    """
    Outcome of cross-checking one claimed gap against a live paper search.

    verdict:
      LIKELY_ADDRESSED — a found paper's title/abstract clearly targets this
                          exact claim; the "gap" is probably not novel.
      UNCERTAIN        — found papers are tangentially related but don't
                          clearly close the gap.
      CONFIRMED_GAP     — nothing relevant turned up (or the search itself
                          failed); treat as provisionally real, not proven.
    """
    claim: str
    search_query: str
    verdict: str
    evidence: str = ""
    reasoning: str = ""
    papers_found: list = field(default_factory=list)  # list[dict]: arxiv_id, title, year
    evidence_span: str = ""       # verbatim phrase the verifier claims supports its verdict
    evidence_verified: bool = True  # False if the citation failed a mechanical check
    evidence_id: str = ""         # id of the cited candidate, as the verifier gave it
    key_terms: list = field(default_factory=list)  # claim subject terms, copied from the claim
    checks: str = ""              # which mechanical checks were applied and their outcome


_GAP_SYSTEM = (
    "You are a careful research reviewer. You identify open problems only from what the "
    "papers in front of you actually report, and you cite the paper for every claim."
)

# Sections are domain-neutral and optional. An earlier version hard-coded ML
# categories ("missing baselines or ablation studies", "scalability or
# efficiency"), which a household-energy-policy run filled with invented
# "ablation studies" because it had no way to leave a section empty.
_GAP_PROMPT = """\
Topic and research brief: "{topic}"

Below are {n_papers} collected papers, numbered [1]..[{n_papers}], with what each paper itself
reports: findings, and limitations and future work quoted from the paper.

{literature_summary}

COLLECTION HEALTH (you MUST reflect this in the report):
{collection_health}

THE BRIEF'S DELIBERATE SCOPE (choices the user made, not gaps):
{brief_scope}

Write a Research Gap Report built from what these papers say, in these sections:

1. OPEN PROBLEMS THE AUTHORS THEMSELVES STATE — from the quoted limitations and future work.
   Group problems several papers raise.
2. DISAGREEMENTS OR CONFLICTING FINDINGS between papers in this collection.
3. SETTINGS, POPULATIONS OR DATA THIS COLLECTION DOES NOT COVER — describe these as gaps in
   this collection, not as gaps in the whole literature. Only list settings inside the brief's
   scope above: a region, population, topic or kind of data the brief deliberately leaves out
   is not a gap.

Rules:
- Every bullet must cite the supporting paper numbers, e.g. [3][7]. A bullet with no citation
  is not allowed.
- Before calling anything unstudied or poorly understood, check the list above: if any
  collected paper addresses it, it is not a gap — say what that paper found instead.
- Never write "no study has", "no research has", or "has never been studied". This collection
  is a sample, not the whole literature.
- If a section has nothing supported by the papers, write exactly: NOT_APPLICABLE
- Do not repeat a point under more than one section.
- If COLLECTION HEALTH lists a critical problem, state it in the first sentence of the report.

Length: 300-500 words."""

_QUESTION_SYSTEM = (
    "You are an expert research advisor who turns gap analyses into concrete, "
    "actionable research questions. Each question must be independently verifiable."
)

_QUESTION_PROMPT = """\
Based on the following research gap analysis for the topic "{topic}", generate 3 to 5 research question candidates.

Gap Analysis:
{gap_analysis}

IMPORTANT: The gap analysis above includes a "Gap Validation" section listing which
claimed gaps were checked against the collected papers and a live literature search. The
verdicts mean different things — do not treat them as interchangeable:
- CONTRADICTED_BY_COLLECTION: papers already collected in this session address it. It is
  not a gap. Do not build a question on it.
- CONFIRMED_GAP: the search found nothing related. This is the strongest basis for a
  novel research question — prefer building questions on these.
- LIKELY_ADDRESSED: a paper already does this. Do not build a question primarily on
  one of these without explicitly acknowledging the prior work found.
- UNCERTAIN: verification could not determine whether the gap is real. This means
  "we don't know", not "this is empty" — it is NOT evidence of novelty. A question
  built on an UNCERTAIN gap must say so explicitly in its Novelty field (e.g. "this
  gap is UNVERIFIED — the check could not confirm or rule it out because ...") and
  must never claim it as an established or confirmed gap.

Also: do not simply restate the user's own stated goals as if you had derived them
from the gap analysis. Each question must be your own synthesis connecting a specific
gap above to a testable question — not a paraphrase (or verbatim copy) of the topic
description you were given.

For EACH question, provide:
- RQ: The research question itself (one clear sentence)
- Feasibility: Can this be tested experimentally? Can it be validated on a single RTX 3060 Ti (8 GB VRAM)?
- Novelty: How is this different from existing work? State which gap verdict
  (CONFIRMED_GAP / LIKELY_ADDRESSED / UNCERTAIN) it is built on, and if UNCERTAIN or
  LIKELY_ADDRESSED, say so plainly rather than implying it is confirmed.
- Effort: Low / Medium / High

Format your response as a numbered list starting with "RQ 1:", "RQ 2:", etc."""

# ---------------------------------------------------------------------------
# Gap validation prompts (Step 3.5)
# ---------------------------------------------------------------------------

_CLAIM_EXTRACTION_SYSTEM = (
    "You extract falsifiable factual claims from a research-gap report. "
    "Return ONLY valid JSON — no markdown, no code fences, no commentary."
)

_CLAIM_EXTRACTION_PROMPT = """\
Below is a Research Gap Report for the topic "{topic}".

{gap_report}

Extract every claim of the form "X has not been done / is missing / is unaddressed / \
is poorly understood / is overlooked / few studies examine X". Ignore vague or non-checkable statements.

For each claim, write:
- search_query: a short literature search query (5-10 words, no boolean operators) that
  would surface papers addressing exactly that gap IF it already exists
- key_terms: 2-3 short terms naming the SUBJECT of the claim, copied exactly from the claim
  wording (e.g. "fuel subsidies", "sustained use"). Never use words describing the gap itself
  such as "lack", "few", "poorly understood", "studies".
- source_papers: the paper numbers the report cites for this claim, e.g. [3, 7]; [] if none

Return a JSON array with at most 6 items, in this exact shape:
[{{"claim": "<one-sentence paraphrase>", "search_query": "<short search query>", "key_terms": ["<term>"], "source_papers": [3]}}]

If there are no checkable claims, return []. Return ONLY the JSON array."""

_EXCLUDED_SCOPE_PROMPT = """\
From the user's constraints below, copy every phrase that names a research TOPIC the user
excludes from scope (for example "stove technology design"). Copy each phrase exactly as
written. Do not include restrictions on data sources, compute, budget or methods.

Constraints:
{constraints}

Return ONLY a JSON array of strings, or [] if there are none."""

# A LIKELY_ADDRESSED citation must be within this cosine similarity of the most
# claim-similar candidate. Measured 2026-09-13 on five real citations: the one
# correct citation was the top candidate; the four wrong ones were 0.052-0.153
# below it. One session's data — revisit as more sessions are checked.
CITATION_MARGIN = 0.05

_GAP_VERIFY_SYSTEM = (
    "You are a skeptical peer reviewer checking whether claimed research gaps are real. "
    "Return ONLY valid JSON — no markdown, no code fences, no commentary."
)

_GAP_VERIFY_PROMPT = """\
For each claim below, decide whether the search evidence shows the "gap" is already \
addressed by existing work. Be skeptical of the CLAIM, not of the evidence: if a found \
paper's title directly targets the same comparison/benchmark/problem, mark it addressed \
even if it doesn't fully solve the problem.

{claims_with_evidence}

Return a JSON array, same order and same length as the input, in this exact shape:
[{{"claim": "<copy the original claim text>",
   "verdict": "LIKELY_ADDRESSED" | "UNCERTAIN" | "CONFIRMED_GAP",
   "evidence_arxiv_id": "<arxiv_id of the ONE paper you are relying on, exactly as given above, or empty string>",
   "evidence_span": "<the EXACT substring copied verbatim from that paper's title above that supports your verdict, or empty string>",
   "reasoning": "<one sentence>"}}]

Verdict rules:
- LIKELY_ADDRESSED: at least one found paper's title clearly targets this exact gap.
- UNCERTAIN: found papers are tangentially related but don't clearly close the gap.
- CONFIRMED_GAP: no found paper is even tangentially related, or the search returned nothing.

CRITICAL: evidence_span must be copied character-for-character from the paper title
given above — do not paraphrase, summarize, or describe what the title "means" or
"mentions". If you cannot find an exact substring in the title that supports your
verdict, use verdict UNCERTAIN and leave evidence_span empty rather than inventing one.
This will be checked programmatically against the actual title text.
Return ONLY the JSON array."""


# --- is the stored gap report still about this session? ------------------------------
# A gap report is an argument about one paper set and one brief. Collecting more
# papers or editing the brief afterwards leaves it on screen looking current,
# and the questions chosen from it inherit that (2026-09-20 report audit).

def gap_context(db, session_id: str) -> dict:
    """What the gap report depended on: the brief and the exact paper set."""
    import hashlib

    session = db.get_session(session_id) or {}
    brief = "\n".join(str(session.get(k) or "") for k in ("topic", "background", "goals", "constraints"))
    papers = db.get_papers(session_id)
    keys = sorted(str(p.get("arxiv_id") or p.get("paper_id") or p.get("title") or "") for p in papers)
    return {"papers": len(papers),
            "paper_key": hashlib.sha256("|".join(keys).encode()).hexdigest()[:16],
            "brief_key": hashlib.sha256(brief.encode()).hexdigest()[:16]}


def record_gap_context(db, session_id: str) -> None:
    """Store that context beside the gap report, so staleness can be seen later."""
    db.save_artifact(session_id, "gap_context", gap_context(db, session_id), "passed")


def gap_staleness(db, session_id: str) -> str:
    """Why the stored gap report no longer matches this session; "" when it still does."""
    session = db.get_session(session_id) or {}
    if not session.get("gap_report"):
        return ""
    art = db.get_artifact(session_id, "gap_context")
    if art is None:
        return ""                      # written before this was recorded: nothing to compare
    then, now = art["content"], gap_context(db, session_id)
    reasons = []
    if then.get("brief_key") != now["brief_key"]:
        reasons.append("the brief was edited")
    if then.get("paper_key") != now["paper_key"]:
        changed = now["papers"] - then.get("papers", 0)
        reasons.append(f"the paper set changed ({then.get('papers', 0)} → {now['papers']} papers)"
                       if changed else "the paper set changed")
    if not reasons:
        return ""
    return ("This gap report was written before " + " and ".join(reasons)
            + ". Re-run the gap analysis before trusting it or the questions taken from it.")


def _echoes_input(rq_text: str, goals_text: str, threshold: float = 0.25) -> bool:
    """
    True if rq_text reuses the user's stated goals nearly word for word —
    measured as the share of the question's 3-word phrases that also appear
    in the goals. A 2026-09-12 run returned the Goals paragraph verbatim as
    "RQ1", labeled as a generated question.

    Measured on the 2026-09-13 run's five questions: a close paraphrase of
    the goals scored 0.40, the three unrelated questions 0.00. The earlier
    version (shared-word ratio against the whole brief, threshold 0.6)
    flagged all five, because any on-topic question shares most vocabulary
    with a 500-word brief. Known limit: a restatement that changes most of
    the wording (0.00 here) is not caught; embedding similarity could not
    separate it from unrelated questions either (0.733 vs 0.711-0.769).
    """
    def trigrams(text: str) -> set[tuple[str, ...]]:
        w = re.findall(r"[a-z]+", text.lower())
        return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}

    rq_grams = trigrams(rq_text)
    if not rq_grams:
        return False
    return len(rq_grams & trigrams(goals_text)) / len(rq_grams) >= threshold


# ---------------------------------------------------------------------------
# Constraint-compliance gate (between question generation and the user)
# ---------------------------------------------------------------------------

_COMPLIANCE_SYSTEM = (
    "You check one research question against the data actually available and the user's "
    "constraints. Answer only in the exact line format requested — no JSON, no commentary."
)

# One question per call, plain-text lines. A 2026-09-13 run asked the local
# 8b model for nested JSON covering five questions at once; it broke the JSON
# and the whole check failed. Line-by-line output fails per line, not per batch.
_COMPLIANCE_PROMPT = """\
AVAILABLE DATA — the only data this question may use:
{schema}

USER CONSTRAINTS (verbatim):
{constraints}

RESEARCH QUESTION:
{question}

List every quantity this question needs (outcomes and explanatory factors), one per line:
NEED: <what the question must measure> | MATCH: <exact code or column name from AVAILABLE DATA, or NONE>

Then one last line:
VIOLATES: <one sentence copied exactly from USER CONSTRAINTS that this question violates, or NONE>

Rules:
- MATCH must be copied exactly from AVAILABLE DATA. If nothing there provides it, write NONE —
  do not substitute a loosely related code.
- MATCH names and VIOLATES quotes are checked programmatically."""

_NONE_VALUES = {"", "none", "n/a", "na", "null", "-"}


def _parse_compliance_text(text: str) -> dict:
    """
    Parse NEED/MATCH and VIOLATES lines. Raises ValueError when neither kind
    of line is present, so an unusable reply is treated as a failed check.
    """
    required: list[dict] = []
    quote = ""
    saw_violates = False
    for raw_line in text.splitlines():
        line = re.sub(r"[*`]+", "", raw_line).strip().lstrip("-• ").strip()
        m = re.match(r"NEED\s*:\s*(.+?)\s*\|\s*MATCH\s*:\s*(.*)$", line, re.I)
        if m:
            matched = m.group(2).strip().strip('"')
            required.append({"need": m.group(1).strip(),
                             "matched": "" if matched.lower() in _NONE_VALUES else matched})
            continue
        m = re.match(r"VIOLATES\s*:\s*(.*)$", line, re.I)
        if m:
            saw_violates = True
            value = m.group(1).strip().strip('"')
            quote = "" if value.lower().rstrip(".") in _NONE_VALUES else value
    if not required and not saw_violates:
        raise ValueError("reply contained no NEED or VIOLATES lines")
    return {"required_variables": required, "violated_constraint_quote": quote}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# A variable mapped to a dataset code must be at least this similar (cosine)
# to the code's meaning. Measured 2026-09-13 on WHO GHO codes, 17 mappings:
# correct ones scored 0.597-0.897, wrong ones 0.357-0.536 — including
# "fuel stacking rates" -> polluting-fuel population (0.530), which the
# existence-only check had passed.
MAPPING_MIN_SIMILARITY = 0.56


def _evaluate_compliance(
    questions: list[ResearchQuestion],
    parsed: list[dict],
    schema,
    constraints: str,
    similarity=None,
) -> list[str]:
    """
    Apply the model's claims mechanically:
    - a variable counts as available only if its "matched" name is in the
      dataset, and — when it is a code with a defined meaning and `similarity`
      is given — that meaning is close enough to what the question needs;
    - a constraint counts as violated only if the quote is really in the constraints.
    Column-name matches can't be checked semantically (names like "TimeDim"
    carry no meaning to compare) and are reported as such.
    Sets each question's compliance fields; returns notes on quotes that were
    not real. `schema=None` means no dataset was available (variables unchecked).
    """
    by_index = {int(p.get("index", 0)): p for p in parsed if isinstance(p, dict)}
    norm_constraints = _normalize(constraints)
    vocabulary = schema.vocabulary() if schema is not None else None
    fabricated: list[str] = []

    for rq in questions:
        result = by_index.get(rq.index)
        if result is None:
            rq.compliance = "fail"
            rq.compliance_notes = "The compliance check returned no result for this question."
            continue

        reasons: list[str] = []
        required = [v for v in result.get("required_variables") or [] if isinstance(v, dict)]
        found: list[str] = []
        if vocabulary is not None:
            if not required:
                reasons.append("could not determine which variables the question needs")
            for v in required:
                need = str(v.get("need", "?"))
                matched = (v.get("matched") or "").strip()
                if not matched or matched.lower() not in vocabulary:
                    reasons.append(f"'{need}' is not in the dataset")
                    continue
                meaning = schema.meaning_of(matched)
                if meaning == matched:
                    found.append(f"{matched} (column name, not semantically checked)")
                    continue
                if similarity is not None:
                    score = similarity(need, meaning)
                    if score < MAPPING_MIN_SIMILARITY:
                        reasons.append(f"'{need}' was mapped to {matched} ({meaning}), which does not "
                                       f"measure it (similarity {score:.2f})")
                        continue
                found.append(f"{matched} = {meaning}")

        quote = (result.get("violated_constraint_quote") or "").strip()
        if quote:
            if _normalize(quote) in norm_constraints:
                reasons.append(f'violates constraint: "{quote}"')
            else:
                fabricated.append(f"RQ {rq.index}: {quote!r}")

        rq.compliance = "fail" if reasons else "pass"
        if reasons:
            rq.compliance_notes = "; ".join(reasons)
        elif vocabulary is None:
            rq.compliance_notes = "No dataset schema available — variables not checked; constraints checked."
        else:
            rq.compliance_notes = f"All required variables found in the dataset: {', '.join(found)}."
    return fabricated


_VERDICTS = ("CONTRADICTED_BY_COLLECTION", "CONFIRMED_GAP", "LIKELY_ADDRESSED", "UNCERTAIN")


def _stem(word: str) -> str:
    if word.endswith("ies") and len(word) >= 6:
        return word[:-3] + "y"
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", text.lower())}


def _paper_stems(p: dict) -> set[str]:
    return _stems(" ".join(str(p.get(k) or "") for k in
                           ("title", "abstract", "findings", "limitation", "future_work")))


def _term_in(term: str, stems: set[str]) -> bool:
    words = [_stem(w) for w in re.findall(r"[a-z]+", term.lower())]
    return bool(words) and all(w in stems for w in words)


def _papers_containing(terms: list[str], papers: list[dict]) -> list[dict]:
    """Papers whose text contains every key term (all words of each term, stemmed)."""
    if not terms:
        return []
    return [p for p in papers if all(_term_in(t, _paper_stems(p)) for t in terms)]


def _reported_stems(p: dict) -> set[str]:
    """What a paper reports doing — not what it says remains to be done."""
    return _stems(" ".join(str(p.get(k) or "") for k in ("title", "abstract", "findings")))


def _source_cutoff_year(claim: dict, collection: list[dict]) -> int | None:
    """Latest publication year among the claim's source papers, or None if it has none."""
    sources = [collection[n - 1] for n in claim.get("source_papers") or [] if 1 <= n <= len(collection)]
    if not sources:
        return None
    years = [int(p.get("year") or 0) for p in sources]
    return max(years) if any(years) else 0


def _contradicting_papers(claim: dict, collection: list[dict]) -> list[dict]:
    """
    Collected papers that show a gap is already closed.

    For a gap taken from papers' own future-work or limitation statements
    (claim["source_papers"] set), the question is recency, not novelty: did
    anyone do it after those papers? So only papers published strictly later
    than the latest source can count, and the source papers themselves never
    do. A 2026-09-13 run marked all six grounded gaps as contradicted — each by
    the very paper that raised it.

    Matching uses title, abstract and findings only. A later paper that also
    says "more research is needed" is a second sign the gap exists, not that
    it closed. Claims with no source papers (free-generated) may be
    contradicted by any paper that reports the work.
    """
    terms = claim.get("key_terms") or []
    if len(terms) < MIN_KEY_TERMS:
        return []  # one term matches any paper on the subject; the check is not valid
    source_numbers = {n for n in claim.get("source_papers") or [] if 1 <= n <= len(collection)}
    cutoff = _source_cutoff_year(claim, collection)

    hits = []
    for n, paper in enumerate(collection, 1):
        if n in source_numbers:
            continue
        if cutoff is not None:
            year = int(paper.get("year") or 0)
            if cutoff == 0 or year <= cutoff:
                continue  # can't show it came after the source
        stems = _reported_stems(paper)
        if all(_term_in(t, stems) for t in terms):
            hits.append(paper)
    return hits


# A collection check needs at least this many key terms. With one ("financial
# costs") any paper on the subject matched (2026-09-13, run e6cb1ae3).
MIN_KEY_TERMS = 2
# Candidate papers asked whether they answer a claim, per claim (one local call each).
MAX_ANSWER_CHECKS = 3

_ANSWER_CHECK_PROMPT = """\
Open problem raised by earlier papers:
"{claim}"

A later paper in the collection: {title} ({year})
What this paper reports:
{reported}

Does this paper REPORT A RESULT that answers the open problem? Mentioning the same topic,
recommending it, or calling for more research does not count.
Answer in exactly two lines:
ANSWERS: yes or no
QUOTE: <one sentence copied word for word from the text above that states that result, or none>"""

_SCOPE_CHECK_PROMPT = """\
The user's research brief sets this scope:
{brief}

A gap report lists this as a setting the paper collection does not cover:
"{bullet}"

Is that setting one the brief deliberately leaves out of scope (a region, population, topic or
kind of data outside the brief's stated topic or constraints)?
Answer in exactly two lines:
OUTSIDE_SCOPE: yes or no
BRIEF_QUOTE: <the words copied exactly from the brief that set that scope, or none>"""

# A quote with this wording recommends or asks for work instead of reporting a result.
_NOT_A_RESULT = re.compile(
    r"\b(should|must|needs?|needed|recommend\w*|propos\w*|future|further research|"
    r"more research|remains?|unknown|unclear|could|would)\b", re.I)


def _parse_labeled(text: str, labels: tuple[str, ...]) -> dict[str, str]:
    """Read "LABEL: value" lines; raises ValueError if a label is missing."""
    out = {}
    for raw_line in text.splitlines():
        line = re.sub(r"[*`]+", "", raw_line).strip().lstrip("-• ").strip()
        for label in labels:
            m = re.match(rf"{label}\s*:\s*(.*)$", line, re.I)
            if m and label not in out:
                out[label] = m.group(1).strip().strip('"')
    missing = [l for l in labels if l not in out]
    if missing:
        raise ValueError(f"reply has no {', '.join(missing)} line")
    return out


def _reported_text(p: dict) -> str:
    return "\n".join(str(p.get(k) or "") for k in ("title", "abstract", "findings") if p.get(k))


def _answer_quote_problem(quote: str, paper: dict, key_terms: list[str]) -> str | None:
    """Why a quote cannot show the paper answered the gap, or None if it can."""
    q = _normalize(quote).rstrip(".")
    if q in _NONE_VALUES or len(q.split()) < 6:
        return "no result sentence quoted"
    if q not in _normalize(_reported_text(paper)):
        return "quote is not in the paper's title, abstract or findings"
    # One sentence rarely repeats every key term word for word ("clean fuel use" for
    # "clean cooking fuel"), so most of their words must appear, not all.
    term_words = {_stem(w) for t in key_terms for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 3}
    if len(term_words & _stems(q)) * 2 < len(term_words):
        return "quote contains fewer than half of the key-term words"
    if _NOT_A_RESULT.search(q):
        return "quote recommends or asks for work rather than reporting a result"
    return None


# Words too general to tie a brief quote to a listed setting ("Open data only"
# would otherwise match any bullet about data).
_GENERIC_WORDS = {"data", "study", "research", "paper", "collection", "cover", "include",
                  "only", "open", "available", "with", "from", "that", "this", "these", "those"}


def _scope_quote_problem(quote: str, brief: str, bullet: str) -> str | None:
    """Why a brief quote cannot show a bullet is out of scope, or None if it can."""
    q = _normalize(quote).rstrip(".")
    if q in _NONE_VALUES or len(q.split()) < 2:
        return "no brief wording quoted"
    if q not in _normalize(brief):
        return "quote is not in the brief"
    if not {w for w in _stems(q) if len(w) > 3 and w not in _GENERIC_WORDS} & _stems(bullet):
        return "quote shares no word with the listed setting"
    return None


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*•]|\d+\.)\s+\S", line))


def _bullet_text(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+\.)\s+", "", line).strip().strip("* ")


def _is_section_heading(line: str) -> bool:
    """Markdown heading, a line that is entirely bold, or an all-capitals line of several words."""
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^#+\s", stripped) or re.fullmatch(r"\*\*[^*]+\*\*:?", stripped):
        return True
    text = re.sub(r"^(?:[-*•#]|\d+\.)\s*", "", stripped).strip("*: ")
    words = re.findall(r"[A-Za-z_]+", re.sub(r"\[\d+\]", "", text))
    return len(words) >= 2 and not re.search(r"[a-z]", text.split("—")[0].split(" - ")[0])


def _papers_containing_any(terms: list[str], papers: list[dict]) -> list[dict]:
    return [p for p in papers if any(_term_in(t, _paper_stems(p)) for t in terms)]


def _find_candidate(evidence_id: str, candidates: list[dict]) -> dict | None:
    """Match a cited id to a candidate, tolerating a missing or extra source prefix."""
    def bare(i: str) -> str:
        i = i.strip().strip("[]").lower()
        for prefix in ("doi:", "epmc:", "openalex:", "openreview:", "s2:", "arxiv:"):
            if i.startswith(prefix):
                return i[len(prefix):]
        return i

    eid = bare(evidence_id or "")
    if not eid:
        return None
    return next((p for p in candidates if bare(str(p.get("arxiv_id", ""))) == eid), None)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def _verify_novelty_labels(
    questions: list[ResearchQuestion], findings: list[GapValidationFinding]
) -> list[str]:
    """
    Check each question's "Novelty: Built on <VERDICT> (<claim>)" against the
    actual gap-validation results, and prefix a visible correction when they
    disagree. Returns one description per corrected question.

    A 2026-09-13 run had two questions claim "Built on CONFIRMED_GAP (fuel
    stacking remains poorly understood...)" when validation had marked that
    exact claim LIKELY_ADDRESSED and no claim at all was CONFIRMED_GAP.
    """
    if not findings:
        return []
    corrected: list[str] = []
    for rq in questions:
        note = rq.novelty_notes or ""
        cited = next((v for v in _VERDICTS if v in note), None)
        if cited is None:
            continue
        cited_claim = note.split(cited, 1)[1]
        m = re.search(r"\(([^)]+)\)", cited_claim)
        claim_tokens = _tokens(m.group(1) if m else cited_claim)

        best, best_score = None, 0.0
        for f in findings:
            ft = _tokens(f.claim)
            if claim_tokens and ft:
                score = len(claim_tokens & ft) / len(claim_tokens | ft)
                if score > best_score:
                    best, best_score = f, score

        if best is not None and best_score >= 0.3:
            actual = best.verdict
        elif not any(f.verdict == cited for f in findings):
            actual = "no claim with that verdict"
        else:
            continue  # can't tell which claim it means; don't guess

        if actual != cited:
            rq.novelty_notes = (
                f"[Label corrected: cited {cited}, but validation result is {actual}] {note}"
            )
            corrected.append(f"RQ {rq.index} cited {cited}, actual {actual}")
    return corrected


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences some models add despite instructions."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


class GapAnalysisAgent:

    def __init__(
        self,
        api_model: "APIModel",
        note_db: "NoteDB",
    ) -> None:
        self._api = api_model
        self._ndb = note_db
        self._deg = None  # lazily set by _ensure_deg(); see agents/degradation.py
        self._reported_sources: set[str] = set()  # sources already logged as skipped
        self._embedder = None          # lazily loaded; tests may inject a fake
        self._embedder_failed = False
        self._reported_unchecked_mapping = False

    def _ensure_deg(self, session_id: str) -> None:
        """
        Lazily wire up the degradation log. Needed because the Web UI path
        (ui/runner.py) calls _analyse_gaps / validate_gap_report directly
        rather than through run(), so it can't rely on run() having set
        this up first.
        """
        if self._deg is None:
            from agents.degradation import DegradationLog
            self._deg = DegradationLog(self._ndb, session_id, notify=console.print)

    # ------------------------------------------------------------------
    def run(
        self,
        topic: str,
        literature_summary: str,
        papers: list["PaperRecord"],
        session_id: str,
    ) -> ResearchQuestion:
        """
        Run gap analysis → generate research questions → ask user to pick one.
        Returns the chosen ResearchQuestion.
        """
        # Step 3: gap analysis — informed by whatever Phase 1 degradations
        # were recorded (thin/arXiv-only collection, ranking that couldn't
        # run, etc.), so the report can't claim "no study exists" over a
        # collection it doesn't know is compromised.
        console.print("\n[bold cyan][Gap Analysis][/] Identifying research gaps (API)…")
        gap_report = self._analyse_gaps(topic, literature_summary, len(papers), session_id)
        console.print(Panel(gap_report, title="Research Gap Report", border_style="yellow"))

        # Step 3.5: validate each claimed gap against a live arXiv search
        console.print(
            "\n[bold cyan][Gap Validation][/] Cross-checking claimed gaps against paper sources…"
        )
        annotated_report, validation = self.validate_gap_report(topic, gap_report, session_id)
        console.print(self._format_validation_summary(validation))
        self._ndb.update_session(
            session_id,
            gap_report=annotated_report,
            gap_validation=json.dumps([vars(v) for v in validation]),
        )

        # Step 4: research question generation (grounded in the validated report)
        console.print("\n[bold cyan][Research Questions][/] Generating candidates (API)…")
        questions = self.generate_checked_questions(topic, annotated_report, validation, session_id)

        if not questions:
            logger.error("No research questions generated.")
            raise RuntimeError("Gap analysis produced no research questions.")

        # Present to user
        chosen = self._present_and_choose(questions)

        # Persist
        self._ndb.update_session(
            session_id,
            research_question=chosen.text,
            status="question_selected",
        )

        return chosen

    # ------------------------------------------------------------------
    def _analyse_gaps(
        self, topic: str, literature_summary: str, n_papers: int, session_id: str
    ) -> str:
        from agents.literature_review import SUMMARY_MAX_CHARS

        self._ensure_deg(session_id)
        cap = SUMMARY_MAX_CHARS + 500
        if len(literature_summary) > cap:
            self._deg.record(3, "gap_analysis", "warn",
                             f"Literature summary truncated from {len(literature_summary)} to "
                             f"{cap} characters; later papers are partly missing from the prompt.")
        health = "\n".join(
            s for s in (self._deg.summary_for_prompt(phase=1), self._deg.summary_for_prompt(phase=2))
            if s != "No degradations recorded."
        ) or "No degradations recorded."
        brief = self._brief_scope(topic, session_id)
        prompt = _GAP_PROMPT.format(
            topic=topic,
            n_papers=n_papers,
            literature_summary=literature_summary[:cap],
            collection_health=health,
            brief_scope=brief,
        )
        report = self._api.generate(
            prompt=prompt,
            system=_GAP_SYSTEM,
            task_type=TaskType.GAP_ANALYSIS,
            temperature=0.3,
        )
        report, out_of_scope = self._remove_out_of_scope_settings(report, brief)
        return self._append_report_checks(report, n_papers, out_of_scope)

    def _brief_scope(self, topic: str, session_id: str) -> str:
        session = self._ndb.get_session(session_id)
        constraints = session.get("constraints") if isinstance(session, dict) else ""
        constraints = constraints.strip() if isinstance(constraints, str) else ""
        return f"Topic: {topic}\nConstraints: {constraints or 'none stated'}"

    def _remove_out_of_scope_settings(self, report: str, brief: str) -> tuple[str, list[tuple[str, str]]]:
        """
        Drop "settings not covered" bullets naming something the brief leaves
        out on purpose. Returns (report, [(bullet, brief quote)]).

        2026-09-13 (run e6cb1ae3): a brief scoped to low- and middle-income
        countries got "the collection does not cover high-income countries" as
        its first uncovered setting. The model must quote the brief wording
        that sets the scope; the quote is checked mechanically, and removed
        bullets are listed in the report checks, not silently deleted.
        """
        removed, kept_lines, in_settings = [], [], False
        for line in report.splitlines():
            if _is_section_heading(line):
                in_settings = bool(re.search(r"SETTINGS|NOT COVER", line, re.I))
            elif in_settings and _is_bullet(line) and "NOT_APPLICABLE" not in line:
                bullet = _bullet_text(line)
                try:
                    raw = self._api.generate(
                        prompt=_SCOPE_CHECK_PROMPT.format(brief=brief, bullet=bullet),
                        system=_GAP_SYSTEM, task_type=TaskType.GAP_ANALYSIS,
                        max_tokens=200, temperature=0.0)
                    reply = _parse_labeled(raw, ("OUTSIDE_SCOPE", "BRIEF_QUOTE"))
                except Exception as exc:
                    if self._deg:
                        self._deg.record(3, "gap_scope_check", "warn",
                                         f"Scope check failed for {bullet[:60]!r} ({exc}); bullet kept.")
                    kept_lines.append(line)
                    continue
                if reply["OUTSIDE_SCOPE"].lower().startswith("yes"):
                    problem = _scope_quote_problem(reply["BRIEF_QUOTE"], brief, bullet)
                    if problem is None:
                        removed.append((bullet, reply["BRIEF_QUOTE"].strip()))
                        continue
                    if self._deg:
                        self._deg.record(3, "gap_scope_check", "info",
                                         f"Kept {bullet[:60]!r}: marked out of scope but {problem}.")
            kept_lines.append(line)
        if removed and self._deg:
            self._deg.record(3, "gap_scope_check", "info",
                             f"Removed {len(removed)} uncovered-setting bullet(s) the brief excludes by design.")
        return "\n".join(kept_lines), removed

    def _append_report_checks(self, report: str, n_papers: int,
                              out_of_scope: list[tuple[str, str]] | None = None) -> str:
        """
        Mechanical checks on the written report: absolute-absence claims
        ("no study has...") and bullets that cite no collected paper. Findings
        are appended to the report and recorded — instructions alone did not
        stop either (a 2026-09-13 run wrote "no study" 9 times after being
        told not to).
        """
        absence = re.compile(
            r"\b(no (?:prior )?(?:study|studies|research|work|paper)s? (?:has|have)|"
            r"(?:has|have) never been (?:studied|examined|evaluated|investigated))\b", re.I)
        sentences = re.split(r"(?<=[.!?])\s+", report)
        absence_hits = [s.strip() for s in sentences if absence.search(s)]

        uncited, out_of_range = [], []
        # A section marked NOT_APPLICABLE has nothing to cite, so bullets under
        # it are not "uncited" (2026-09-13, run e6cb1ae3 flagged them).
        not_applicable = False
        for ln in report.splitlines():
            if _is_section_heading(ln):
                not_applicable = "NOT_APPLICABLE" in ln
                continue
            if "NOT_APPLICABLE" in ln:
                not_applicable = True
                continue
            if not_applicable or not _is_bullet(ln):
                continue
            b = ln.strip()
            text = _bullet_text(ln)
            if text.endswith(":") or not re.search(r"[a-z]", re.sub(r"\[\d+\]", "", text)):
                continue
            nums = [int(n) for n in re.findall(r"\[(\d+)\]", b)]
            if not nums:
                uncited.append(b)
            elif any(n < 1 or n > n_papers for n in nums):
                out_of_range.append(b)

        if not (absence_hits or uncited or out_of_range or out_of_scope):
            return report
        lines = ["", "## Automated report checks"]
        if out_of_scope:
            lines.append("Removed from SETTINGS NOT COVERED — the brief excludes these on purpose:")
            lines += [f'- {b} (brief: "{q}")' for b, q in out_of_scope]
        if absence_hits:
            lines.append("Absolute-absence claims (this collection is a sample; treat as unverified):")
            lines += [f"- {s}" for s in absence_hits]
        if uncited:
            lines.append("Bullets citing no collected paper:")
            lines += [f"- {b}" for b in uncited]
        if out_of_range:
            lines.append(f"Bullets citing paper numbers outside [1]-[{n_papers}]:")
            lines += [f"- {b}" for b in out_of_range]
        if self._deg and (absence_hits or uncited or out_of_range):
            self._deg.record(
                3, "gap_report_checks", "warn",
                f"{len(absence_hits)} absolute-absence claim(s), {len(uncited)} uncited bullet(s), "
                f"{len(out_of_range)} bullet(s) citing nonexistent papers.",
            )
        return report.rstrip() + "\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Step 3.5: Gap validation
    # ------------------------------------------------------------------

    def validate_gap_report(
        self, topic: str, gap_report: str, session_id: str
    ) -> tuple[str, list[GapValidationFinding]]:
        """
        Check every falsifiable gap claim, in this order:
        1. Against this session's own collected papers. Papers that report
           every key term (at least two) are candidates; one counts only if
           the model quotes a result sentence from it that passes the
           mechanical quote checks (_confirmed_answer). Then the claim is
           CONTRADICTED_BY_COLLECTION — a 2026-09-13 report called fuel
           stacking "poorly understood" while holding six stacking papers.
        2. Only the remaining claims are searched externally. Results in the
           user's excluded scope are dropped, the rest ranked by similarity to
           the claim, and the model picks a verdict from those.
        3. Any LIKELY_ADDRESSED citation is then checked mechanically: the
           cited paper must be a real candidate, the quoted span must be in its
           title, it must contain a key term, and it must be among the most
           claim-similar candidates. Otherwise it is downgraded to UNCERTAIN.

        Never raises: failures degrade to fewer or UNCERTAIN findings, recorded.
        Returns (report with a "## Gap Validation" section, findings).
        """
        self._ensure_deg(session_id)
        report_body = gap_report.split("\n## Automated report checks")[0]
        try:
            claims = self._extract_claims(topic, report_body)
        except Exception as exc:
            logger.warning("Gap claim extraction failed, skipping validation: %s", exc)
            if self._deg:
                self._deg.record(3, "gap_validation", "critical",
                                 f"Claim extraction failed ({exc}); no gap was validated.")
            return gap_report, []

        if not claims:
            return gap_report, []

        collection = self._ndb.get_papers(session_id)
        collection = collection if isinstance(collection, list) else []
        contradicted, remaining = [], []
        for c in claims:
            if len(c["key_terms"]) < MIN_KEY_TERMS:
                c["collection_note"] = (f"collection check not run: fewer than {MIN_KEY_TERMS} key terms "
                                        f"({', '.join(c['key_terms']) or 'none'})")
                remaining.append(c)
                continue
            hits = _contradicting_papers(c, collection)
            answer = self._confirmed_answer(c, hits[:MAX_ANSWER_CHECKS]) if hits else None
            if answer is None:
                terms = ", ".join(c["key_terms"])
                c["collection_note"] = (
                    f"{len(hits)} collected paper(s) mention every key term ({terms}) but none was shown "
                    "to report a result answering it" if hits else
                    f"no eligible collected paper reports every key term ({terms})")
                remaining.append(c)
                continue
            paper, quote = answer
            cutoff = _source_cutoff_year(c, collection)
            scope = f"published after its source paper(s) ({cutoff})" if cutoff else "in this collection"
            contradicted.append(GapValidationFinding(
                claim=c["claim"],
                search_query=c["search_query"],
                verdict="CONTRADICTED_BY_COLLECTION",
                evidence=f"{paper.get('title', '')} ({paper.get('year')}): \"{quote}\"",
                reasoning="",
                key_terms=c["key_terms"],
                checks=f"paper {scope}; quoted result found verbatim in its title/abstract/findings, "
                       f"contains a key term, is not a recommendation (mechanical)",
            ))

        excluded = self._excluded_topics(session_id) if remaining else []
        for c in remaining:
            candidates = self._search_evidence(c.get("search_query", ""))
            cutoff = _source_cutoff_year(c, collection)
            if cutoff:
                # A future-work gap is closed only by work published after it was raised.
                candidates = [p for p in candidates if int(p.get("year") or 0) > cutoff]
            c["papers_found"] = self._filter_candidates(c, candidates, excluded)

        external: list[GapValidationFinding] = []
        if remaining:
            try:
                external = self._verify_claims(remaining)
            except Exception as exc:
                logger.warning("Gap verification failed, marking all UNCERTAIN: %s", exc)
                if self._deg:
                    self._deg.record(3, "gap_validation", "critical",
                                     f"Verification call failed ({exc}); every claim marked UNCERTAIN.")
                external = [
                    GapValidationFinding(
                        claim=c.get("claim", ""),
                        search_query=c.get("search_query", ""),
                        verdict="UNCERTAIN",
                        reasoning=f"Verification call failed: {exc}",
                        papers_found=c.get("papers_found", []),
                        key_terms=c.get("key_terms", []),
                    )
                    for c in remaining
                ]
            external = self._verify_evidence_spans(external)
            notes = {c["claim"]: c["collection_note"] for c in remaining if c.get("collection_note")}
            for f in external:
                if f.claim in notes:
                    f.checks = notes[f.claim] + (f"; {f.checks}" if f.checks else "")

        by_claim = {f.claim: f for f in contradicted + external}
        findings = [by_claim[c["claim"]] for c in claims if c["claim"] in by_claim]
        annotated = gap_report.rstrip() + "\n\n" + self._render_validation_section(findings)
        return annotated, findings

    def _confirmed_answer(self, claim: dict, papers: list[dict]) -> tuple[dict, str] | None:
        """
        The first paper whose reported text answers the claim, with the quoted
        result sentence, or None.

        Sharing the claim's key terms only makes a paper a candidate: a paper
        discussing fuel costs naturally contains "fuel costs" and "clean cooking
        fuel" without having answered anything (2026-09-13, run e6cb1ae3: all six
        gaps closed this way). The model must quote the sentence that reports the
        result, and the quote is checked mechanically.
        """
        for paper in papers:
            prompt = _ANSWER_CHECK_PROMPT.format(
                claim=claim["claim"], title=paper.get("title", ""), year=paper.get("year", ""),
                reported=_reported_text(paper)[:3000])
            try:
                raw = self._api.generate(prompt=prompt, system=_GAP_SYSTEM,
                                         task_type=TaskType.NOVELTY_CHECK, max_tokens=300, temperature=0.0)
                reply = _parse_labeled(raw, ("ANSWERS", "QUOTE"))
            except Exception as exc:
                if self._deg:
                    self._deg.record(3, "gap_validation", "warn",
                                     f"Answer check failed for {paper.get('title', '')[:60]!r} ({exc}); "
                                     "that paper was not counted as closing the gap.")
                continue
            if not reply["ANSWERS"].lower().startswith("yes"):
                continue
            problem = _answer_quote_problem(reply["QUOTE"], paper, claim["key_terms"])
            if problem is None:
                return paper, reply["QUOTE"].strip()
            if self._deg:
                self._deg.record(3, "gap_validation", "info",
                                 f"Rejected collection evidence {paper.get('title', '')[:60]!r} for "
                                 f"{claim['claim'][:60]!r}: {problem}.")
        return None

    # --- evidence filtering ------------------------------------------------------

    def _get_embedder(self):
        """Ollama embedding model, or None (recorded once) if unavailable."""
        if self._embedder is None and not self._embedder_failed:
            try:
                from models.ollama_model import OllamaEmbedModel
                emb = OllamaEmbedModel()
                emb.load()
                self._embedder = emb
            except Exception as exc:
                self._embedder_failed = True
                if self._deg:
                    self._deg.record(3, "embedding_backend", "warn",
                                     f"No embedding model ({exc}); relevance and excluded-scope "
                                     f"checks on validation evidence are skipped.")
        return self._embedder

    def _similarity(self, a: str, b: str) -> float | None:
        emb = self._get_embedder()
        if emb is None:
            return None
        import numpy as np
        va, vb = np.asarray(emb.embed(a), dtype=float), np.asarray(emb.embed(b), dtype=float)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        return float(va @ vb / denom) if denom else 0.0

    def _excluded_topics(self, session_id: str) -> list[str]:
        """Topic phrases the user's constraints exclude, copied verbatim (verified)."""
        session = self._ndb.get_session(session_id)
        constraints = session.get("constraints") if isinstance(session, dict) else ""
        if not isinstance(constraints, str) or not constraints.strip():
            return []
        try:
            raw = self._api.generate_structured(
                prompt=_EXCLUDED_SCOPE_PROMPT.format(constraints=constraints),
                system=_CLAIM_EXTRACTION_SYSTEM,
                task_type=TaskType.NOVELTY_CHECK,
            )
            parsed = json.loads(_strip_json_fences(raw))
        except Exception as exc:
            if self._deg:
                self._deg.record(3, "excluded_scope", "warn",
                                 f"Could not read excluded topics from constraints ({exc}).")
            return []
        norm_constraints = _normalize(constraints)
        phrases = [str(p).strip() for p in parsed if isinstance(p, str)] if isinstance(parsed, list) else []
        verified = [p for p in phrases if len(p) > 3 and _normalize(p) in norm_constraints]
        if len(verified) < len(phrases) and self._deg:
            self._deg.record(3, "excluded_scope", "warn",
                             f"Ignored {len(phrases) - len(verified)} excluded-topic phrase(s) "
                             f"not found verbatim in the constraints.")
        return verified

    def _filter_candidates(self, claim: dict, candidates: list[dict], excluded: list[str]) -> list[dict]:
        """
        Drop candidates closer to an excluded topic than to the claim, then rank
        by similarity to the claim, keeping those within RELEVANCE_MARGIN of the
        best. Measured 2026-09-13: an injera stove combustion paper scored 0.641
        against "stove technology design" and 0.600 against the claim it was
        cited for; a clean-cookstove trial scored 0.532 vs 0.625 and is kept.
        """
        import config

        if not candidates or self._get_embedder() is None:
            return candidates
        text = claim["claim"]
        kept, dropped_scope = [], []
        for p in candidates:
            doc = f"{p.get('title', '')}. {p.get('abstract', '')[:500]}"
            sim = self._similarity(text, doc)
            p["similarity"] = round(sim, 3)
            if any((self._similarity(neg, doc) or 0.0) > sim for neg in excluded):
                dropped_scope.append(p.get("title", ""))
                continue
            kept.append(p)
        if dropped_scope and self._deg:
            self._deg.record(3, "excluded_scope", "info",
                             f"Dropped {len(dropped_scope)} candidate(s) in excluded scope for "
                             f"{text[:60]!r}: " + " | ".join(t[:60] for t in dropped_scope))
        if not kept:
            return []
        kept.sort(key=lambda p: -p["similarity"])
        cutoff = kept[0]["similarity"] - config.RELEVANCE_MARGIN
        return [p for p in kept if p["similarity"] >= cutoff][:10]

    def _verify_evidence_spans(
        self, findings: list["GapValidationFinding"]
    ) -> list["GapValidationFinding"]:
        """
        Mechanically check every LIKELY_ADDRESSED citation and downgrade it to
        UNCERTAIN unless all hold:
        - the cited id is one of the candidates shown (with or without a
          source prefix such as "doi:")
        - the quoted span occurs in that paper's title
        - that paper's title/abstract contains at least one key term of the claim
        - its similarity to the claim is within CITATION_MARGIN of the best candidate

        The last two exist because checking the span alone passed an injera
        stove paper, a hypertension study and a cardiovascular study as
        evidence for claims about cooking-fuel interventions: the quoted words
        were really in those titles, the "the title mentions X" reasoning was
        invented. Margin measured 2026-09-13: those three cited papers sat
        0.052-0.153 below the best candidate; the correctly cited paper was the best.
        """
        for f in findings:
            if f.verdict != "LIKELY_ADDRESSED":
                continue
            span = (f.evidence_span or "").strip()
            cited = _find_candidate(f.evidence_id, f.papers_found)
            problem = None
            if cited is None:
                problem = f"cited paper {f.evidence_id!r} is not among the candidates"
            elif not span or span.lower() not in (cited.get("title") or "").lower():
                problem = f"quoted span {span!r} does not occur in the cited paper's title"
            elif f.key_terms and not _papers_containing_any(f.key_terms, [cited]):
                problem = f"cited paper contains none of the claim's key terms ({', '.join(f.key_terms)})"
            elif "similarity" in cited:
                best = max(p.get("similarity", 0.0) for p in f.papers_found)
                if best - cited["similarity"] > CITATION_MARGIN:
                    problem = (f"cited paper is {best - cited['similarity']:.3f} less similar to the "
                               f"claim than the best candidate")

            if cited is not None:
                f.evidence = f"[{cited.get('arxiv_id')}] {cited.get('title', '')}"
            if problem is None:
                f.checks = "citation checks passed (in candidates, span in title, key term, top similarity)"
                continue

            fabricated = cited is None or problem.startswith("quoted span")
            f.verdict = "UNCERTAIN"
            f.evidence_verified = False
            f.checks = f"downgraded from LIKELY_ADDRESSED: {problem}"
            if self._deg:
                self._deg.record(
                    3, "gap_validation", "critical" if fabricated else "warn",
                    ("Fabricated evidence" if fabricated else "Irrelevant evidence")
                    + f" for claim {f.claim!r}: {problem}. Verdict downgraded to UNCERTAIN.",
                )
        return findings

    def _extract_claims(self, topic: str, gap_report: str) -> list[dict]:
        prompt = _CLAIM_EXTRACTION_PROMPT.format(topic=topic, gap_report=gap_report[:8000])
        raw = self._api.generate_structured(
            prompt=prompt,
            system=_CLAIM_EXTRACTION_SYSTEM,
            task_type=TaskType.NOVELTY_CHECK,
        )
        parsed = json.loads(_strip_json_fences(raw))
        if not isinstance(parsed, list):
            raise ValueError(f"Expected a JSON array, got {type(parsed)}")
        claims = [c for c in parsed if isinstance(c, dict) and c.get("claim") and c.get("search_query")][:6]
        for c in claims:
            # Key terms must come from the claim itself, so the collection check
            # can't be steered by words the model added.
            claim_norm = _normalize(c["claim"])
            terms = c.get("key_terms") if isinstance(c.get("key_terms"), list) else []
            c["key_terms"] = [str(t).strip() for t in terms if str(t).strip() and _normalize(str(t)) in claim_norm][:4]
            # Source numbers must actually be cited in the report as "[n]".
            sources = c.get("source_papers") if isinstance(c.get("source_papers"), list) else []
            valid = []
            for n in sources:
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    continue
                if f"[{n}]" in gap_report and n not in valid:
                    valid.append(n)
            c["source_papers"] = valid
        return claims

    def _search_evidence(self, search_query: str) -> list[dict]:
        """Best-effort search across all configured paper sources. Never raises."""
        if not search_query:
            return []
        try:
            from tools.sources import search_all
            papers, problems = search_all(search_query, limit=5)
        except Exception as exc:
            logger.warning("Gap-validation search failed for %r: %s", search_query, exc)
            return []
        if self._deg:
            for source, reason in problems.items():
                if source not in self._reported_sources:
                    self._reported_sources.add(source)
                    self._deg.record(3, f"source:{source}", "warn",
                                     f"{source} not used for gap validation: {reason}")
        return [
            {"arxiv_id": p.arxiv_id, "title": p.title, "year": p.year,
             "abstract": getattr(p, "abstract", "") or ""}
            for p in papers
        ]

    def _verify_claims(self, claims: list[dict]) -> list[GapValidationFinding]:
        blocks = []
        for i, c in enumerate(claims, 1):
            papers = c.get("papers_found", [])
            evidence_text = (
                "\n".join(f"  - [{p['arxiv_id']}] {p['title']} ({p['year']})" for p in papers)
                if papers else "  (no results found)"
            )
            blocks.append(
                f"{i}. Claim: {c['claim']}\n   Search query used: \"{c['search_query']}\"\n"
                f"   Papers found:\n{evidence_text}"
            )
        prompt = _GAP_VERIFY_PROMPT.format(claims_with_evidence="\n\n".join(blocks))
        raw = self._api.generate_structured(
            prompt=prompt,
            system=_GAP_VERIFY_SYSTEM,
            task_type=TaskType.NOVELTY_CHECK,
        )
        parsed = json.loads(_strip_json_fences(raw))
        if not isinstance(parsed, list):
            raise ValueError(f"Expected a JSON array, got {type(parsed)}")

        findings = []
        for i, c in enumerate(claims):
            v = parsed[i] if i < len(parsed) else {}
            findings.append(GapValidationFinding(
                claim=c["claim"],
                search_query=c["search_query"],
                verdict=v.get("verdict", "UNCERTAIN"),
                reasoning=v.get("reasoning", ""),
                papers_found=c.get("papers_found", []),
                evidence_span=v.get("evidence_span", ""),
                evidence_id=str(v.get("evidence_arxiv_id", "") or ""),
                key_terms=c.get("key_terms", []),
            ))
        return findings

    @staticmethod
    def _render_validation_section(findings: list[GapValidationFinding]) -> str:
        if not findings:
            return (
                "## Gap Validation (automated cross-check)\n"
                "No checkable claims were extracted, or validation could not run."
            )
        lines = ["## Gap Validation (automated cross-check)",
                 "Each claimed gap was checked against this session's collected papers first, "
                 "then against an external search.\n"]
        for f in findings:
            lines.append(f"**[{f.verdict}]** {f.claim}")
            if f.evidence:
                lines.append(f"  Evidence: {f.evidence}")
            if f.checks:
                lines.append(f"  Checks: {f.checks}")
            if f.reasoning:
                lines.append(f"  Model's reasoning (not verified): {f.reasoning}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_validation_summary(findings: list[GapValidationFinding]) -> str:
        if not findings:
            return "[dim]No checkable gap claims were extracted.[/]"
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.verdict] = counts.get(f.verdict, 0) + 1
        return (
            f"Checked {len(findings)} claim(s): "
            f"[red]{counts.get('CONTRADICTED_BY_COLLECTION', 0)} contradicted by the collection[/], "
            f"[red]{counts.get('LIKELY_ADDRESSED', 0)} likely already addressed[/], "
            f"[yellow]{counts.get('UNCERTAIN', 0)} uncertain[/], "
            f"[green]{counts.get('CONFIRMED_GAP', 0)} confirmed gap[/]."
        )

    def _generate_questions(
        self,
        topic: str,
        gap_analysis: str,
        validation: list[GapValidationFinding] | None = None,
        goals: str = "",
    ) -> list[ResearchQuestion]:
        """`goals` is the user's Goals field; falls back to `topic` when empty."""
        prompt = _QUESTION_PROMPT.format(
            topic=topic,
            gap_analysis=gap_analysis[:6000],
        )
        raw = self._api.generate(
            prompt=prompt,
            system=_QUESTION_SYSTEM,
            task_type=TaskType.RESEARCH_QUESTION,
            temperature=0.7,
        )
        questions = self._parse_questions(raw)

        for rq in questions:
            if _echoes_input(rq.text, goals or topic):
                rq.echoes_input = True
        echoed = [rq.index for rq in questions if rq.echoes_input]
        if echoed and self._deg:
            self._deg.record(
                3, "research_question", "warn",
                f"RQ {echoed} reuse the user's stated goals nearly word for word rather "
                f"than deriving a question from the gap analysis — flagged, not blocked."
            )

        mislabeled = _verify_novelty_labels(questions, validation or [])
        if mislabeled and self._deg:
            self._deg.record(
                3, "novelty_label", "warn",
                "Research questions cited validation verdicts that don't match the "
                "actual results: " + "; ".join(mislabeled)
            )
        return questions

    # ------------------------------------------------------------------
    # Constraint-compliance gate
    # ------------------------------------------------------------------

    def generate_checked_questions(
        self,
        topic: str,
        gap_analysis: str,
        validation: list[GapValidationFinding],
        session_id: str,
        max_rounds: int = 3,
    ) -> list[ResearchQuestion]:
        """
        Generate questions, reject any that need variables absent from the
        declared dataset or that violate the user's constraints, and regenerate
        in place of rejected ones. Only passing questions reach the user; if
        none pass after `max_rounds`, the last round is returned with each
        failure reason shown, so the user is never shown an unexplained "Yes".
        """
        self._ensure_deg(session_id)
        session = self._ndb.get_session(session_id)
        session = session if isinstance(session, dict) else {}
        goals = session.get("goals") or ""
        constraints = session.get("constraints") or ""

        if getattr(self._api, "_api_available", True) is False:
            self._deg.record(
                3, "data_check", "warn",
                "Data check ran on the local model (Anthropic API unavailable or disabled); "
                "variable mapping from a small local model is less reliable.",
            )

        result: list[ResearchQuestion] = []
        try:
            with self._deg.phase(3, "data_check") as gate:
                schema = self._load_declared_schema(session)
                result = self._run_check_rounds(
                    topic, gap_analysis, validation, goals, constraints, schema, max_rounds
                )
                unchecked = [q for q in result if q.compliance == "unchecked"]
                if not result:
                    gate.fail("no research questions were produced")
                elif unchecked:
                    gate.fail(f"{len(unchecked)} of {len(result)} question(s) could not be checked: "
                              + " | ".join(q.compliance_notes for q in unchecked))
                elif all(q.compliance == "fail" for q in result):
                    gate.fail(f"no research question passed after {max_rounds} round(s); "
                              f"showing the last round with failure reasons")
                else:
                    gate.ok()
        finally:
            # Labels are applied on every exit path — including when the check
            # itself failed — so no question is shown with only the model's "Yes".
            for i, q in enumerate(result, 1):
                q.index = i
                q.feasibility_notes = (
                    f"[Data check {q.compliance.upper()}] {q.compliance_notes}"
                    + (f" — model's own note: {q.feasibility_notes}" if q.feasibility_notes else "")
                )
        return result

    def _run_check_rounds(
        self, topic, gap_analysis, validation, goals, constraints, schema, max_rounds
    ) -> list[ResearchQuestion]:
        passed: list[ResearchQuestion] = []
        unchecked: list[ResearchQuestion] = []
        rejected_notes: list[str] = []
        last_round: list[ResearchQuestion] = []
        for round_no in range(max_rounds):
            feedback = ""
            if rejected_notes:
                feedback = (
                    "Questions already rejected for needing unavailable data or violating the "
                    "constraints — do not repeat them or close variants:\n"
                    + "\n".join(f"- {n}" for n in rejected_notes) + "\n\n"
                )
            questions = self._generate_questions(topic, feedback + gap_analysis, validation, goals=goals)
            if not questions:
                continue
            last_round = questions
            self._check_compliance(questions, schema, constraints)

            seen = {_normalize(q.text) for q in passed + unchecked}
            for q in questions:
                if _normalize(q.text) in seen:
                    continue
                if q.compliance == "pass":
                    passed.append(q)
                elif q.compliance == "unchecked":
                    unchecked.append(q)
                else:
                    rejected_notes.append(f"{q.text} — {q.compliance_notes}")
                seen.add(_normalize(q.text))
            failed = [q for q in questions if q.compliance == "fail"]
            if failed:
                self._deg.record(
                    3, "data_check", "info",
                    f"Round {round_no + 1}: rejected {len(failed)} question(s): "
                    + " | ".join(f"{q.text[:80]} ({q.compliance_notes})" for q in failed),
                )
            if len(passed) + len(unchecked) >= 3 or not failed:
                break

        shown = (passed + unchecked)[:5]
        return shown if shown else last_round

    def _load_declared_schema(self, session: dict):
        """Schema of the first dataset URL in the brief, or None (recorded)."""
        from tools.dataset_schema import DatasetUnavailable, find_dataset_urls, load_schema
        from tools.rate_limit import SourceBlocked

        urls = find_dataset_urls(
            session.get("background") or "", session.get("goals") or "", session.get("constraints") or ""
        )
        if not urls:
            if self._deg:
                self._deg.record(3, "dataset_schema", "warn",
                                 "No dataset URL (.zip/.csv/.tsv) found in the brief — research "
                                 "questions are checked against constraints only, not data columns.")
            return None
        problems = []
        for url in urls:
            try:
                return load_schema(url)
            except (DatasetUnavailable, SourceBlocked) as exc:
                problems.append(str(exc))
        if self._deg:
            self._deg.record(3, "dataset_schema", "warn",
                             "Declared dataset could not be read (" + "; ".join(problems) + ") — "
                             "research questions are checked against constraints only.")
        return None

    def _check_compliance(self, questions: list[ResearchQuestion], schema, constraints: str) -> None:
        """
        Check each question in its own call. A question whose check can't run
        (exception or unparseable reply) is marked "unchecked" — never passed.
        """
        parsed: list[dict] = []
        checkable: list[ResearchQuestion] = []
        for q in questions:
            prompt = _COMPLIANCE_PROMPT.format(
                schema=schema.describe() if schema else "(no dataset schema available)",
                constraints=constraints or "(none given)",
                question=q.text,
            )
            try:
                raw = self._api.generate_structured(
                    prompt=prompt, system=_COMPLIANCE_SYSTEM, task_type=TaskType.FEASIBILITY_EVAL,
                )
                parsed.append({"index": q.index, **_parse_compliance_text(raw)})
                checkable.append(q)
            except Exception as exc:
                q.compliance, q.compliance_notes = "unchecked", f"check could not run ({exc})"

        if not checkable:
            return
        similarity = self._similarity if (schema is not None and self._get_embedder()) else None
        if schema is not None and similarity is None and not self._reported_unchecked_mapping:
            self._reported_unchecked_mapping = True
            self._deg.record(3, "data_check", "warn",
                             "No embedding model: variable-to-code mappings are checked for existence "
                             "only, not for whether the code measures what the question needs.")
        fabricated = _evaluate_compliance(checkable, parsed, schema, constraints, similarity)
        if fabricated:
            self._deg.record(3, "data_check", "warn",
                             "Constraint quotes not found in the user's constraints (ignored): "
                             + "; ".join(fabricated))

    @staticmethod
    def _parse_questions(raw: str) -> list[ResearchQuestion]:
        """
        Parse the numbered RQ list from the API response.
        Format expected:
          RQ 1: ...
          - Feasibility: ...
          - Novelty: ...
          - Effort: ...
        """
        questions: list[ResearchQuestion] = []
        # Markdown emphasis leaked into displayed questions on 2026-09-13
        # ("**RQ:** What ...", "Feasibility: ** Yes"), so strip it first.
        cleaned = re.sub(r"\*+", "", raw)
        blocks = re.split(r'\bRQ\s*\d+\s*:', cleaned, flags=re.IGNORECASE)
        for i, block in enumerate(blocks[1:], 1):  # skip preamble
            lines = block.strip().split("\n")
            rq_text = re.sub(r"^RQ\s*:\s*", "", lines[0].strip(), flags=re.IGNORECASE)
            rest = "\n".join(lines[1:])

            feasibility = ""
            novelty = ""
            m = re.search(r'feasibility\s*:\s*(.+?)(?:\n|$)', rest, re.IGNORECASE)
            if m:
                feasibility = m.group(1).strip()
            m = re.search(r'novelty\s*:\s*(.+?)(?:\n|$)', rest, re.IGNORECASE)
            if m:
                novelty = m.group(1).strip()

            questions.append(ResearchQuestion(
                index=i,
                text=rq_text,
                feasibility_notes=feasibility,
                novelty_notes=novelty,
            ))

        return questions

    # ------------------------------------------------------------------
    def _present_and_choose(
        self, questions: list[ResearchQuestion]
    ) -> ResearchQuestion:
        console.print("\n[bold green]=== Research Question Candidates ===[/]\n")

        for rq in questions:
            console.print(
                f"[bold]{rq.index}.[/] {rq.text}\n"
                f"   [dim]Feasibility:[/] {rq.feasibility_notes}\n"
                f"   [dim]Novelty:[/]     {rq.novelty_notes}\n"
            )

        console.print(
            "[dim]Enter a number to select, or type your own research question:[/]"
        )

        while True:
            answer = Prompt.ask("Your choice").strip()

            # Check if it's a number
            if answer.isdigit():
                idx = int(answer)
                if 1 <= idx <= len(questions):
                    return questions[idx - 1]
                console.print(
                    f"[red]Please enter a number between 1 and {len(questions)}.[/]"
                )
            elif answer:
                # Custom research question
                return ResearchQuestion(
                    index=0,
                    text=answer,
                    feasibility_notes="User-defined",
                    novelty_notes="User-defined",
                )
            else:
                console.print("[red]Please enter a selection or custom question.[/]")
