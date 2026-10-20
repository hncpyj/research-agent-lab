"""
Where a result came from.

A finished session hands back a report. The question a reader should always be
able to ask -- what is this built on? -- had no answer except reading the whole
session: which papers fed the gap report, which gap became the question, which
hypothesis the plan tested, which run produced the table the claims are checked
against, and where along that chain something was degraded.

Nothing new is recorded to answer it. Every link already exists in the stored
rows: papers belong to a session, artifacts are versioned per stage, claims
carry the hash of the results table they were checked against, the review
carries the hash of the claims it reviewed. This module reads those and states
the chain, with the degradations attached to the step they happened in.

A step that never ran is absent rather than empty: an honest graph of what was
actually done is more useful than a diagram of the pipeline.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The order work happens in, and what each step is made from. Only steps that
# exist in the session become nodes; an edge is drawn when both ends exist.
LINEAGE = {
    "brief": [],
    "papers": ["brief"],
    "source_check": ["papers"],
    "review_lit": ["papers"],
    "gap_report": ["review_lit", "papers"],
    "question": ["gap_report"],
    "data_audit": ["question"],
    "hypotheses": ["question", "data_audit"],
    "plan": ["hypotheses", "data_audit"],
    "assembly": ["plan"],
    "run": ["assembly", "plan"],
    "results": ["run"],
    "claims": ["results"],
    "report": ["claims", "results"],
    "review": ["report", "claims"],
    "code": ["hypotheses"],
    "experiment_runs": ["code"],
}

# Which step a recorded degradation belongs to, by the component that wrote it.
DEGRADATION_STEP = {
    "canon_seeding": "papers",
    "paper_collection": "papers",
    "source_check": "source_check",
    "gap_validation": "gap_report",
    "gap_analysis": "gap_report",
    "api_budget": "brief",
    "run_interrupted": "brief",
    "imported_papers": "papers",
    "imported_question": "question",
    "imported_gap_report": "gap_report",
    "data_audit": "data_audit",
    "analysis": "run",
    "report": "report",
}

LABELS = {
    "brief": "Brief",
    "papers": "Papers",
    "source_check": "Source check",
    "review_lit": "Literature review",
    "gap_report": "Gap report",
    "question": "Research question",
    "data_audit": "Data audit",
    "hypotheses": "Hypotheses",
    "plan": "Analysis plan",
    "assembly": "Assembled script",
    "run": "Analysis run",
    "results": "Results table",
    "claims": "Checked claims",
    "report": "Report",
    "review": "Review",
    "code": "Experiment code",
    "experiment_runs": "Experiment runs",
}


def _node(step: str, **fields) -> dict:
    return {"id": step, "label": LABELS.get(step, step), **fields}


def graph(db, session_id: str) -> dict:
    """
    The chain behind this session: nodes for the steps that actually ran, edges
    for what each was made from, and the degradations that happened at each.
    """
    session = db.get_session(session_id)
    if session is None:
        raise ValueError(f"no session {session_id!r}")

    nodes: dict[str, dict] = {}

    nodes["brief"] = _node("brief", kind="input", status="given",
                           created_at=session.get("created_at", ""),
                           detail={"topic": session.get("topic", ""),
                                   "goals": session.get("goals") or "",
                                   "constraints": session.get("constraints") or ""})

    papers = db.get_papers(session_id)
    if papers:
        by_source: dict[str, int] = {}
        for p in papers:
            by_source[p.get("source") or "unknown"] = by_source.get(p.get("source") or "unknown", 0) + 1
        nodes["papers"] = _node("papers", kind="collection", status="done", count=len(papers),
                                created_at=min(p.get("created_at", "") for p in papers),
                                detail={"by_source": by_source,
                                        "with_fulltext": sum(1 for p in papers if p.get("text_source"))})

    if session.get("gap_report"):
        nodes["gap_report"] = _node("gap_report", kind="document", status="done",
                                    created_at=session.get("updated_at", ""),
                                    detail={"characters": len(session["gap_report"] or ""),
                                            "validated": bool(session.get("gap_validation"))})

    if session.get("research_question"):
        nodes["question"] = _node("question", kind="decision", status="chosen",
                                  created_at=session.get("updated_at", ""),
                                  detail={"text": session["research_question"]})

    # The study path: one node per stage that has an artifact, carrying how
    # many times it was rebuilt and whether a person approved it.
    for art in db.list_artifacts(session_id):
        step = art["stage"]
        if step not in LINEAGE:
            continue
        # The version number is how many times this stage has been built: the
        # listing carries only the latest row of each.
        nodes[step] = _node(step, kind="artifact", status=art["status"],
                            approved=bool(art["approved"]), versions=art["version"],
                            created_at=art["created_at"],
                            detail=_artifact_detail(step, art))

    hypotheses = db.get_hypotheses(session_id)
    if hypotheses and "hypotheses" not in nodes:
        nodes["hypotheses"] = _node("hypotheses", kind="collection", status="done",
                                    count=len(hypotheses),
                                    created_at=min(h.get("created_at", "") for h in hypotheses),
                                    detail={"selected": sum(1 for h in hypotheses
                                                            if h.get("status") == "selected")})

    code = [c for h in hypotheses for c in db.get_experiment_code(h["hypothesis_id"])]
    if code:
        nodes["code"] = _node("code", kind="collection", status="done", count=len(code),
                              created_at=min(c.get("created_at", "") for c in code),
                              detail={"files": [c["file_path"] for c in code][:10]})

    runs = db.get_experiment_runs(session_id)
    if runs:
        nodes["experiment_runs"] = _node(
            "experiment_runs", kind="collection", status=runs[-1].get("status", ""),
            count=len(runs), created_at=runs[0].get("started_at", ""),
            detail={"phases": sorted({r.get("phase", "") for r in runs}),
                    "failed": sum(1 for r in runs if r.get("status") not in ("success", "passed"))})

    _attach_degradations(db, session_id, nodes)
    edges = _edges(nodes)
    _mark_broken_links(nodes, db, session_id)

    # In the order the work happens, not the order the rows were written: a
    # stage rebuilt last is still the same step of the study.
    order = list(LINEAGE)
    ordered = sorted(nodes.values(), key=lambda n: order.index(n["id"]))
    return {"session_id": session_id, "nodes": ordered, "edges": edges,
            "complete": "report" in nodes or "experiment_runs" in nodes}


def _artifact_detail(step: str, art: dict) -> dict:
    """A few honest numbers per stage, never the whole document."""
    content = art.get("content")
    if not isinstance(content, dict):
        return {}
    detail: dict = {}
    if step == "results":
        rows = content.get("rows")
        detail["rows"] = len(rows) if isinstance(rows, list) else 0
    if step == "claims":
        claims = content.get("claims")
        detail["claims"] = len(claims) if isinstance(claims, list) else 0
        detail["results_hash"] = (content.get("results_hash") or "")[:12]
    if step == "report":
        detail["results_hash"] = (content.get("results_hash") or "")[:12]
        detail["title"] = content.get("title", "")
    if step == "review":
        findings = content.get("findings")
        detail["findings"] = len(findings) if isinstance(findings, list) else 0
        detail["claims_hash"] = (content.get("claims_hash") or "")[:12]
    if step == "hypotheses":
        items = content.get("hypotheses")
        detail["hypotheses"] = len(items) if isinstance(items, list) else 0
    if step == "source_check":
        problems = content.get("problems")
        detail["problems"] = len(problems) if isinstance(problems, list) else 0
    return detail


def _attach_degradations(db, session_id: str, nodes: dict) -> None:
    for entry in db.get_degradations(session_id):
        step = DEGRADATION_STEP.get(entry["component"])
        if step is None or step not in nodes:
            step = "brief"                        # still shown, on the session itself
        nodes[step].setdefault("degradations", []).append(
            {"severity": entry["severity"], "component": entry["component"],
             "message": entry["message"], "created_at": entry["created_at"]})


def _edges(nodes: dict) -> list[dict]:
    edges = []
    for step, sources in LINEAGE.items():
        if step not in nodes:
            continue
        for source in sources:
            if source in nodes:
                edges.append({"from": source, "to": step})
    return edges


def _mark_broken_links(nodes: dict, db, session_id: str) -> None:
    """
    The two places the chain can be checked rather than assumed: claims carry
    the hash of the results they were checked against, and the review carries
    the hash of the claims it reviewed. A mismatch means what is on screen was
    built from something that has since been rebuilt, and saying so is the
    whole point of keeping the hashes.
    """
    def content_hash(stage):
        art = db.get_artifact(session_id, stage)
        return (art or {}).get("content_hash", "")

    pairs = [("claims", "results", "results_hash"), ("review", "claims", "claims_hash")]
    for step, source, field in pairs:
        if step not in nodes or source not in nodes:
            continue
        recorded = (nodes[step].get("detail") or {}).get(field, "")
        actual = content_hash(source)[:12]
        if recorded and actual and recorded != actual:
            nodes[step]["stale"] = True
            nodes[step].setdefault("degradations", []).append(
                {"severity": "critical", "component": f"{step}_stale",
                 "message": f"This {LABELS[step].lower()} was built from an earlier "
                            f"{LABELS[source].lower()}, which has since been rebuilt.",
                 "created_at": nodes[step].get("created_at", "")})


def project_graph(db, sessions: list[dict]) -> dict:
    """
    A project seen as a body of work: each session with how far it got, and the
    papers any two of them share. Shared reading is what makes several sessions
    one project rather than a list of attempts.
    """
    from memory import paper_index

    ids = [s["session_id"] for s in sessions]
    nodes = []
    for s in sessions:
        papers = paper_index.count_for([s["session_id"]])
        nodes.append({"id": s["session_id"], "label": s.get("topic", ""),
                      "status": s.get("status", ""), "created_at": s.get("created_at", ""),
                      "papers": papers,
                      "has_report": bool(s.get("report"))})
    return {"nodes": nodes,
            "edges": [{"from": e["left_id"], "to": e["right_id"], "shared_papers": e["shared"]}
                      for e in paper_index.sessions_sharing(ids)],
            "papers": paper_index.count_for(ids)}
