"""
Stage S2 — data audit memo.

Before any hypothesis is written, record what the declared dataset can and
cannot measure: every indicator with its meaning, unit, country and year
coverage, the splits it has, and the country groupings available. Computed
from the data itself; no language model.

Background (2026-09-13, session c5a020c3): both hypotheses were built on
"energy policy stringency", a variable the WHO download does not contain,
because hypothesis generation never saw the data.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from tools.panel_data import (PanelDataError, PanelLayout, _read_raw, country_rows,
                              detect_layout, indicator_codes)

logger = logging.getLogger(__name__)


class DataAuditError(Exception):
    """The declared dataset cannot be audited; later stages must not run."""


def _unit_of(meaning: str) -> str:
    text = meaning.lower()
    if "%" in text or "proportion" in text or "percent" in text:
        return "%"
    for group in re.findall(r"\(([^)]*)\)", meaning):
        if re.search(r"\bper\b|million|thousand|rate", group, re.I):
            return group
    return "not stated"


def declared_dataset(session: dict):
    """(url, schema, local path) for the first readable dataset URL in the brief, or None if none is declared."""
    from tools.dataset_schema import DatasetUnavailable, cached_path, find_dataset_urls, load_schema
    from tools.rate_limit import SourceBlocked

    urls = find_dataset_urls(session.get("background") or "", session.get("goals") or "",
                             session.get("constraints") or "")
    if not urls:
        return None
    problems = []
    for url in urls:
        try:
            return url, load_schema(url), cached_path(url)
        except (DatasetUnavailable, SourceBlocked) as exc:
            problems.append(f"{url}: {exc}")
    raise DataAuditError("declared dataset could not be read: " + "; ".join(problems))


MAX_INDICATORS = 30


def build_audit(schema, path: Path, question: dict, max_indicators: int = MAX_INDICATORS) -> dict:
    """The memo as a dict. Raises DataAuditError."""
    try:
        layout = detect_layout(schema, path)
    except PanelDataError as exc:
        raise DataAuditError(f"unsupported data layout: {exc}") from exc

    meanings = schema.meanings
    indicators = []
    codes = indicator_codes(layout, schema)
    # A file whose indicators are columns is read once, not once per indicator:
    # the 127-column OWID energy file took 21 s of re-reading otherwise.
    shared = None
    if layout.kind == "indicator_columns" and codes:
        try:
            shared = country_rows(layout, _read_raw(layout, codes[0])).copy()
        except PanelDataError as exc:
            raise DataAuditError(f"could not read {path.name}: {exc}") from exc

    for code in codes:
        if shared is not None:
            raw = shared.dropna(subset=[code])
        else:
            try:
                raw = _read_raw(layout, code)
            except PanelDataError as exc:
                logger.warning("Audit could not read %s: %s", code, exc)
                continue
            raw = country_rows(layout, raw[raw[layout.indicator_column] == code])
        if raw.empty:
            continue
        years = pd.to_numeric(raw[layout.time_column], errors="coerce")
        per_unit = raw.assign(_t=years).groupby(layout.unit_column)["_t"].nunique()
        splits = {}
        for col in layout.dimension_columns:
            if col in raw.columns:
                present = sorted(raw[col].dropna().astype(str).unique())
                if present:
                    splits[col] = [{"code": c, "meaning": meanings.get(c, c)} for c in present]
        bounds = [c for c in ("Low", "High") if c in raw.columns and raw[c].notna().any()]
        meaning = meanings.get(code, code)
        indicators.append({
            "code": code, "meaning": meaning, "unit": _unit_of(meaning),
            "n_countries": int(raw[layout.unit_column].nunique()),
            "years": [int(years.min()), int(years.max())],
            "median_years_per_country": float(per_unit.median()),
            "splits": splits,
            "uncertainty_bounds": bool(bounds),
        })
    if not indicators:
        raise DataAuditError("no indicator has country-level rows")

    indicators, omitted = _shortlist(indicators, question, max_indicators)

    groups = {}
    for col in layout.attribute_columns:
        codes = sorted(v for v in schema.values.get(col, set()) if v in meanings)
        groups[col] = [{"code": c, "meaning": meanings[c]} for c in codes]

    limits = []
    for ind in indicators:
        if ind["years"][0] == ind["years"][1]:
            limits.append(f"{ind['code']} covers a single year ({ind['years'][0]}): no trend analysis possible.")
    attributable = [i["code"] for i in indicators if "attributable" in i["meaning"].lower()]
    if attributable:
        # Paper [19] of session c5a020c3 used registry deaths for this reason.
        limits.append(f"{', '.join(attributable)} are attributable-burden estimates, which are usually modelled "
                      "from exposure; relating them to fuel-use indicators can be circular.")
    limits.append("How the values were produced (survey, model estimate) is not stated in the dataset files; "
                  "check the provider's indicator metadata before treating them as measurements.")
    if layout.unit_rule:
        limits.append(f"Country rows are {layout.unit_rule}; regional and world aggregates are left out, "
                      "and dependent territories with their own code are counted as units.")
    if omitted:
        limits.append(f"This dataset has {len(indicators) + omitted} indicators; the {len(indicators)} listed "
                      "here are the ones closest to the research question, by best coverage. A hypothesis "
                      "about any of the other " + str(omitted) + " cannot be written from this memo — "
                      "narrow the question, or ask for those indicators by name.")

    return {
        "source": schema.url,
        "indicators_omitted": omitted,
        "layout": layout.as_dict(),
        "units": {"kind": "country", "column": layout.unit_column, "rule": layout.unit_rule},
        "indicators": indicators,
        "groups": groups,
        "limits": limits,
        "question": question,
    }


def _shortlist(indicators: list[dict], question: dict, limit: int) -> tuple[list[dict], int]:
    """
    Which indicators the memo lists when the dataset has more than fit in one
    prompt. Ordered by how many words of the research question the indicator's
    name carries, then by coverage. What was left out is counted, never
    silently dropped — the reader is told in the memo's limits.
    """
    if limit <= 0 or len(indicators) <= limit:
        return indicators, 0
    words = {w for w in re.findall(r"[a-z]{4,}", (question.get("text") or "").lower())}

    def rank(ind: dict) -> tuple:
        name = f"{ind['code']} {ind['meaning']}".lower()
        hits = sum(1 for w in words if w in name or w.rstrip("s") in name)
        coverage = ind["n_countries"] * max(ind["median_years_per_country"], 1)
        return (-hits, -coverage, ind["code"])

    ordered = sorted(indicators, key=rank)
    return sorted(ordered[:limit], key=lambda i: i["code"]), len(indicators) - limit


def describe_for_prompt(audit: dict) -> str:
    lines = ["Indicators (use the code as the variable):"]
    for ind in audit["indicators"]:
        splits = "; ".join(f"{col}: " + ", ".join(f"{s['code']} ({s['meaning']})" for s in codes)
                           for col, codes in ind["splits"].items())
        lines.append(f"- {ind['code']}: {ind['meaning']} [unit {ind['unit']}; {ind['n_countries']} countries; "
                     f"{ind['years'][0]}-{ind['years'][1]}]" + (f"\n  splits — {splits}" if splits else ""))
    for col, codes in audit["groups"].items():
        lines.append(f"Country groups — {col}: " + ", ".join(f"{g['code']} ({g['meaning']})" for g in codes))
    lines.append("Also available: UNIT (the country) and TIME (the year).")
    lines += [f"Limit: {l}" for l in audit["limits"]]
    return "\n".join(lines)


def layout_of(audit: dict) -> PanelLayout:
    return PanelLayout.from_dict(audit["layout"])
