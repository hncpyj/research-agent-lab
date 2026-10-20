"""
Stage S3 — hypotheses with an operationalization table.

Each hypothesis must say, row by row, which variable in the data audit (S2)
measures each concept it relies on. Rows are checked mechanically: the code
or column exists, and the concept is semantically close to what the code
means. A hypothesis with any row that fails is kept and shown as untestable,
and cannot go on to the analysis plan. The user picks which testable
hypotheses to study.

Replaces agents/hypothesis.py for sessions with a declared dataset. That
agent asked for ablations and GPU hours, never saw the data, parsed JSON from
an 8b model with a silent fallback, and chose a hypothesis by the model's own
feasibility score (2026-09-13, session c5a020c3).
"""

from __future__ import annotations

import logging
import re

from router import TaskType

logger = logging.getLogger(__name__)

# Concept ↔ code-meaning cosine (nomic-embed-text). Measured 2026-09-13: correct
# indicator mappings 0.597-0.897, wrong 0.357-0.536 (17 mappings); on 2026-09-14
# splits and groups: correct 0.491-0.887, wrong 0.340-0.459 (15 pairs). Rows
# between 0.46 and 0.56 are rejected — a stricter choice that can mark a vaguely
# worded concept ("place of residence", 0.491) untestable, with its score shown.
MAPPING_MIN_SIMILARITY = 0.56

_SYSTEM = ("You are a careful quantitative researcher. You only propose hypotheses that the "
           "listed variables can test, and you say plainly what they cannot test.")

_PROMPT = """\
Research question: {question}

The user's goals: {goals}
The user's constraints: {constraints}

WHAT THE DATA CAN MEASURE:
{audit}

WHAT COLLECTED PAPERS FOUND (context only):
{findings}

Write 2 to 4 hypotheses that answer the research question using ONLY the variables above.
Do not invent variables. If part of the question needs something the data does not have
(for example policies, prices or income), write it in CANNOT_TEST instead.

Use exactly this format for each hypothesis:
HYPOTHESIS: H1
STATEMENT: <one falsifiable sentence>
ROW: concept=<concept in plain English> | variable=<variable> | expect=<expected pattern>
ROW: concept=... | variable=... | expect=...
CANNOT_TEST: <what the question asks that these variables cannot measure, or none>

A variable is one of:
- an indicator code, e.g. PHE_HHAIR_PROP_POP_CLEAN_FUELS
- a split or country group with its codes, e.g. DisaggregatingDimension1ValueCode:RESIDENCEAREATYPE_URB,RESIDENCEAREATYPE_RUR
- UNIT (the country) or TIME (the year)
Every hypothesis needs at least one indicator row."""


def _parse(raw: str) -> list[dict]:
    hypotheses, current = [], None
    for line in raw.splitlines():
        line = re.sub(r"[*`]+", "", line).strip().lstrip("-• ").strip()
        m = re.match(r"HYPOTHESIS\s*:\s*(H\d+)", line, re.I)
        if m:
            current = {"id": m.group(1).upper(), "statement": "", "rows": [], "cannot_test": ""}
            hypotheses.append(current)
            continue
        if current is None:
            continue
        if re.match(r"STATEMENT\s*:", line, re.I):
            current["statement"] = line.split(":", 1)[1].strip()
        elif re.match(r"CANNOT_TEST\s*:", line, re.I):
            value = line.split(":", 1)[1].strip()
            current["cannot_test"] = "" if value.lower().rstrip(".") in ("none", "n/a", "") else value
        elif re.match(r"ROW\s*:", line, re.I):
            fields = {}
            for part in line.split(":", 1)[1].split("|"):
                key, _, value = part.partition("=")
                fields[key.strip().lower()] = value.strip()
            extra = {k: v for k, v in fields.items() if k not in ("concept", "variable", "expect") and v}
            current["rows"].append({"concept": fields.get("concept", ""), "variable": fields.get("variable", ""),
                                    "expect": fields.get("expect", ""), "extra": extra})
    seen, unique = set(), []
    for h in hypotheses:  # a model sometimes repeats an id; keep the first
        if h["id"] not in seen and h["statement"]:
            seen.add(h["id"])
            unique.append(h)
    return unique


class HypothesisDesigner:
    def __init__(self, api_model, embedder=None, deg=None) -> None:
        self._api = api_model
        self._embedder = embedder
        self._deg = deg

    # --- generation ------------------------------------------------------------
    def generate(self, question: str, session: dict, audit_text: str, papers: list[dict]) -> tuple[list[dict], str]:
        findings = "\n".join(f"[{i}] {p.get('title', '')}: {(p.get('findings') or '')[:220]}"
                             for i, p in enumerate(papers, 1) if p.get("findings")) or "(none extracted)"
        prompt = _PROMPT.format(question=question, goals=(session.get("goals") or "not stated")[:1200],
                                constraints=(session.get("constraints") or "not stated")[:1500],
                                audit=audit_text, findings=findings[:3000])
        raw = self._api.generate(prompt=prompt, system=_SYSTEM, task_type=TaskType.HYPOTHESIS_GEN,
                                 max_tokens=2000, temperature=0.4)
        hypotheses = _parse(raw)
        if not hypotheses:
            retry = prompt + "\n\nYour previous reply had no HYPOTHESIS/STATEMENT lines. Use the format exactly."
            raw = self._api.generate(prompt=retry, system=_SYSTEM, task_type=TaskType.HYPOTHESIS_GEN,
                                     max_tokens=2000, temperature=0.2)
            hypotheses = _parse(raw)
        return hypotheses, raw

    # --- checks ----------------------------------------------------------------
    def _vector(self, text: str):
        import numpy as np
        cache = self.__dict__.setdefault("_vectors", {})
        if text not in cache:
            cache[text] = np.asarray(self._embedder.embed(text), dtype=float)
        return cache[text]

    def _similarity(self, a: str, b: str) -> float | None:
        if self._embedder is None:
            return None
        import numpy as np
        va, vb = self._vector(a), self._vector(b)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        return float(va @ vb / denom) if denom else 0.0

    def check(self, hypotheses: list[dict], audit: dict, papers: list[dict]) -> list[dict]:
        indicators = {i["code"]: i for i in audit["indicators"]}
        splits = {}
        for ind in audit["indicators"]:
            for col, codes in ind["splits"].items():
                splits.setdefault(col, {}).update({c["code"]: c["meaning"] for c in codes})
        groups = {col: {g["code"]: g["meaning"] for g in codes} for col, codes in audit["groups"].items()}
        if self._embedder is None and self._deg:
            self._deg.record(4, "hypothesis_mapping", "critical",
                             "No embedding model: concept-to-variable meanings were not checked; "
                             "every hypothesis is marked untestable.")

        for h in hypotheses:
            problems = []
            for row in h["rows"]:
                row.update(self._check_row(row, indicators, splits, groups))
                if not row["problem"]:
                    row["problem"] = self._check_qualifier(row, indicators, splits)
                if not row["problem"]:
                    self._infer_split(row, indicators)
                if row["problem"]:
                    problems.append(f"{row['concept'] or row['variable']}: {row['problem']}")
            used = [indicators[r["variable"].strip()] for r in h["rows"]
                    if r.get("kind") == "indicator" and not r["problem"]]
            if not used:
                problems.append("no indicator row maps to the data")
            for row in h["rows"]:
                col, _, codes_text = row["variable"].partition(":")
                col, codes = col.strip(), {c.strip() for c in codes_text.split(",") if c.strip()}
                has_split = lambda ind: codes <= {s["code"] for s in ind["splits"].get(col, [])}
                if row.get("kind") == "split" and not row["problem"] and not any(has_split(i) for i in used):
                    row["problem"] = f"none of this hypothesis' indicators is split by {col}:{','.join(sorted(codes))}"
                    problems.append(f"{row['concept'] or row['variable']}: {row['problem']}")
            h["problems"] = problems
            h["testable"] = not problems
            h["similar_papers"] = self._similar_papers(h["statement"], papers)
        return hypotheses

    def _check_row(self, row: dict, indicators: dict, splits: dict, groups: dict) -> dict:
        variable = row["variable"].strip()
        if variable.upper() in ("UNIT", "TIME"):
            return {"kind": variable.lower(), "meaning": "country" if variable.upper() == "UNIT" else "year",
                    "similarity": None, "problem": ""}
        if ":" in variable:
            col, _, codes_text = variable.partition(":")
            col, codes = col.strip(), [c.strip() for c in codes_text.split(",") if c.strip()]
            table, kind = (splits, "split") if col in splits else (groups, "group") if col in groups else (None, None)
            if table is None:
                return {"kind": "unknown", "meaning": "", "similarity": None,
                        "problem": f"column {col} is not a split or country group in the data"}
            unknown = [c for c in codes if c not in table[col]]
            if not codes or unknown:
                return {"kind": kind, "meaning": "", "similarity": None,
                        "problem": f"codes not in {col}: {', '.join(unknown) or 'none given'}"}
            meaning = "; ".join(table[col][c] for c in codes)
        elif variable in indicators:
            kind, meaning = "indicator", indicators[variable]["meaning"]
        else:
            return {"kind": "unknown", "meaning": "", "similarity": None,
                    "problem": f"{variable or 'empty variable'} is not an indicator code in the data"}

        sim = self._similarity(row["concept"], meaning) if row["concept"] else 0.0
        if sim is None:
            return {"kind": kind, "meaning": meaning, "similarity": None, "problem": "meaning not checked"}
        problem = "" if sim >= MAPPING_MIN_SIMILARITY else (
            f"concept does not match what the variable measures ({meaning}; similarity {sim:.2f})")
        return {"kind": kind, "meaning": meaning, "similarity": round(sim, 3), "problem": problem}

    @staticmethod
    def _infer_split(row: dict, indicators: dict) -> None:
        """
        A concept that names a split of its indicator ("Urban clean fuel share")
        but whose row selects none measured the total series instead — seen with
        llama3.1:8b on 2026-09-14, and the concept still passed the similarity
        check (0.58). The split named in the wording is attached and marked inferred.
        """
        if row.get("kind") != "indicator" or row.get("split") or row.get("extra"):
            return
        concept = row["concept"].lower()
        for col, codes in indicators[row["variable"].strip()]["splits"].items():
            named = [c["code"] for c in codes
                     if c["meaning"].lower() not in ("total", "both sexes")
                     and re.search(rf"\b{re.escape(c['meaning'].lower())}\b", concept)]
            if named:
                row["split"] = f"{col}:{','.join(named)}"
                row["split_inferred"] = True
                return

    @staticmethod
    def _check_qualifier(row: dict, indicators: dict, splits: dict) -> str:
        """
        Extra ROW fields such as "split=RESIDENCEAREATYPE_URB". The 8b model adds
        them although the format has none (2026-09-14); ignoring them passed a
        death-rate indicator as split by urban/rural when it is split only by sex.
        They are resolved and checked against that indicator's own splits.
        """
        extra = row.get("extra") or {}
        if not extra:
            return ""
        if row.get("kind") != "indicator":
            return f"unrecognised fields {', '.join(extra)} on a non-indicator row"
        own = indicators[row["variable"].strip()]["splits"]
        resolved = []
        for key, value in extra.items():
            col, _, codes_text = value.rpartition(":")
            codes = [c.strip() for c in codes_text.split(",") if c.strip()]
            cols = [col.strip()] if col.strip() else [c for c in own if all(x in {s["code"] for s in own[c]} for x in codes)]
            match = next((c for c in cols if c in own and all(x in {s["code"] for s in own[c]} for x in codes)), None)
            if not codes or match is None:
                return f"{row['variable']} has no split {value} ({key})"
            resolved.append(f"{match}:{','.join(codes)}")
        row["split"] = resolved[0]
        return ""

    def _similar_papers(self, statement: str, papers: list[dict]) -> list[dict]:
        """The collected papers closest to the hypothesis, for the user to judge overlap — not a gate."""
        if self._embedder is None:
            return []
        scored = []
        for i, p in enumerate(papers, 1):
            text = f"{p.get('title', '')}. {p.get('findings') or p.get('abstract') or ''}"[:800]
            sim = self._similarity(statement, text)
            if sim is not None:
                scored.append({"number": i, "title": p.get("title", ""), "similarity": round(sim, 3)})
        return sorted(scored, key=lambda s: -s["similarity"])[:3]
