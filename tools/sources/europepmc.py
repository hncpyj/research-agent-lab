"""Europe PMC article search — biomedical and global-health literature (includes PubMed)."""

from __future__ import annotations

import re
import urllib.parse

from tools.arxiv_fetcher import PaperRecord
from tools.sources._http import request_json, request_text

SOURCE = "europepmc"
_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def search(query: str, limit: int) -> list[PaperRecord]:
    params = urllib.parse.urlencode({
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": limit,
    })
    data = request_json(SOURCE, f"{_BASE}?{params}")
    results = (data.get("resultList") or {}).get("result", [])
    return [r for r in (_to_record(a) for a in results) if r]


def _to_record(a: dict) -> PaperRecord | None:
    title = re.sub(r"<[^>]+>", "", a.get("title") or "").strip().rstrip(".")
    if not title:
        return None
    src, pid = a.get("source", ""), a.get("id", "")
    try:
        year = int(a.get("pubYear") or 0)
    except ValueError:
        year = 0
    # Full text is retrievable only for open-access articles with a PMCID.
    pmcid = a.get("pmcid") or ""
    fulltext_id = pmcid if pmcid and a.get("isOpenAccess") == "Y" else ""
    return PaperRecord(
        arxiv_id=f"epmc:{src}:{pid}",
        title=title,
        authors=[s.strip() for s in (a.get("authorString") or "").rstrip(".").split(",") if s.strip()],
        year=year,
        url=f"https://europepmc.org/article/{src}/{pid}",
        abstract=re.sub(r"<[^>]+>", " ", a.get("abstractText") or "").strip(),
        doi=a.get("doi") or "",
        source=SOURCE,
        fulltext_id=fulltext_id,
    )


def fetch_fulltext_sections(pmcid: str) -> dict[str, str]:
    """
    Open-access full text (JATS XML) → {section title: text} for sections that
    carry an article's own statement of what remains open: discussion,
    limitations, conclusions, future work. Paced and block-aware like all
    source requests. Endpoint: /rest/{PMCID}/fullTextXML.
    """
    import xml.etree.ElementTree as ET

    xml = request_text(SOURCE, f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
    root = ET.fromstring(xml)
    wanted = re.compile(r"discussion|limitation|conclusion|future|implication|strength", re.I)
    sections: dict[str, str] = {}
    for sec in root.iter("sec"):
        title_el = sec.find("title")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        if not wanted.search(title):
            continue
        paragraphs = [" ".join("".join(p.itertext()).split()) for p in sec.iter("p")]
        text = " ".join(p for p in paragraphs if p)
        if text:
            sections[title] = text
    return sections
