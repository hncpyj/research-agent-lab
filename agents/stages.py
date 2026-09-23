"""
What each stage needs, what it leaves behind, and whether it can run now.

The pipeline was one road: start at a topic, end at a report. People arrive
with different halves of the work already done — one wants only the paper
search, one has their own papers and wants the gap analysis, one has the whole
study and wants the write-up. That works only if every stage states its
requirements out loud, so the session can be checked against them and the
missing pieces can be supplied by hand (memory/importing.py).

Nothing here runs anything. It answers three questions about a session:
what has been done, what could run now, and what is missing for the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# What a requirement is, in one place, so the UI and the runners agree.
# Each entry: how to see whether a session has it, and how a person can supply
# it without running the stage that normally produces it.
REQUIREMENTS: dict[str, dict] = {
    "papers":      {"label": "collected papers", "supply": "import a paper list (CSV, JSON or BibTeX)"},
    "review":      {"label": "literature review notes", "supply": "run the review stage, or import papers that already carry findings"},
    "gap_report":  {"label": "a gap report", "supply": "paste your own gap report"},
    "question":    {"label": "a research question", "supply": "write the question yourself"},
    "dataset":     {"label": "a dataset named in the brief", "supply": "put the dataset URL in the brief's background"},
    "data_audit":  {"label": "the data audit memo", "supply": "run the audit stage (it reads the declared dataset)"},
    "hypotheses":  {"label": "selected hypotheses", "supply": "run the hypotheses stage and choose, at the gate"},
    "plan":        {"label": "an approved analysis plan", "supply": "paste a plan at the plan gate and approve it"},
    "results":     {"label": "a results table", "supply": "run the analysis, or import a session bundle that has one"},
    "claims":      {"label": "checked claims", "supply": "run the report stage"},
    "report":      {"label": "a written report", "supply": "run the report stage"},
}


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    needs: tuple[str, ...]
    provides: tuple[str, ...]
    status_after: str            # the session status this stage reaches
    path: str = "common"         # common | study | ml
    gate: str = ""               # the gate it stops at, if any
    note: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "needs": list(self.needs),
                "provides": list(self.provides), "path": self.path,
                "gate": self.gate, "note": self.note}


STAGES: tuple[Stage, ...] = (
    Stage("papers", "Collect papers", (), ("papers",), "papers_collected",
          note="Searches the configured sources, paced 20-30 s apart."),
    Stage("review", "Review the literature", ("papers",), ("review",), "review_done",
          note="Reads each paper for findings and limitations."),
    Stage("gaps", "Find gaps and write questions", ("papers",), ("gap_report", "question"),
          "question_selected", gate="question_selection",
          note="Checks each claimed gap against the collected papers, then stops for you to pick a question."),
    Stage("audit", "Audit the dataset", ("dataset", "question"), ("data_audit",), "data_audited",
          path="study", note="Computed from the data; no model is called."),
    Stage("hypotheses", "Write hypotheses", ("data_audit",), ("hypotheses",), "hypotheses_selected",
          path="study", gate="hypothesis_selection",
          note="Every concept must map to a variable in the data."),
    Stage("plan", "Write the analysis plan", ("hypotheses",), ("plan",), "plan_approved",
          path="study", gate="plan_approval",
          note="Fixes what counts as supported or rejected before any number is seen."),
    Stage("analysis", "Run the analysis", ("plan", "data_audit"), ("results",), "experiment_run",
          path="study", note="Assembles tested blocks and runs them; no model-written code."),
    Stage("report", "Write claims and the report", ("results",), ("claims", "report"), "report_written",
          path="study", note="Only claims that survive the checks reach the report."),
    Stage("review_report", "Review against the plan", ("report",), ("review_notes",), "reviewed",
          path="study", note="Checks the report against the plan and the results."),
)

BY_KEY: dict[str, Stage] = {s.key: s for s in STAGES}

# A session that has reached one of these statuses has done that much.
STATUS_ORDER: tuple[str, ...] = (
    "started", "papers_collected", "review_done", "question_selected", "data_audited",
    "hypotheses_generated", "hypotheses_selected", "plan_approved", "code_generated",
    "experiment_run", "report_written", "reviewed",
)


def _has(db, session_id: str, requirement: str) -> bool:
    """Whether this session already holds one requirement."""
    session = db.get_session(session_id) or {}
    if requirement == "papers":
        return bool(db.get_papers(session_id))
    if requirement == "review":
        return any((p.get("findings") or p.get("limitation")) for p in db.get_papers(session_id))
    if requirement == "gap_report":
        return bool(session.get("gap_report"))
    if requirement == "question":
        return bool(session.get("research_question"))
    if requirement == "dataset":
        from tools.dataset_schema import find_dataset_urls
        return bool(find_dataset_urls(session.get("background") or "", session.get("goals") or "",
                                      session.get("constraints") or ""))
    stage_artifacts = {"data_audit": "data_audit", "hypotheses": "hypotheses", "plan": "plan",
                       "results": "results", "claims": "claims", "report": "report"}
    stage = stage_artifacts.get(requirement)
    if stage is None:
        return False
    art = db.get_artifact(session_id, stage)
    if art is None or art["status"] not in ("passed", "awaiting_approval"):
        return False
    if requirement == "hypotheses":
        return bool(art["content"].get("selected"))       # written is not chosen
    if requirement == "plan":
        return bool(art.get("approved"))
    return art["status"] == "passed"


def readiness(db, session_id: str) -> list[dict]:
    """
    Every stage with: is it done, can it run now, and if not, what is missing
    and how the missing piece can be supplied by hand.
    """
    session = db.get_session(session_id) or {}
    status = session.get("status", "started")
    reached = STATUS_ORDER.index(status) if status in STATUS_ORDER else -1

    rows = []
    for stage in STAGES:
        missing = [r for r in stage.needs if not _has(db, session_id, r)]
        # "Done" means its output exists. A stage whose output has no separate
        # record (the review notes) is judged by how far the session got —
        # without this, an empty session counted it as done.
        checkable = [r for r in stage.provides if r in REQUIREMENTS]
        done = bool(checkable) and all(_has(db, session_id, r) for r in checkable)
        if not done and stage.status_after in STATUS_ORDER:
            done = reached >= STATUS_ORDER.index(stage.status_after)
        rows.append({
            **stage.as_dict(),
            "done": done,
            "ready": not missing,
            "missing": [{"key": m, "label": REQUIREMENTS[m]["label"], "supply": REQUIREMENTS[m]["supply"]}
                        for m in missing],
        })
    return rows


def blocking(db, session_id: str, stage_key: str) -> list[str]:
    """What stops this stage from running now; empty means it can run."""
    stage = BY_KEY.get(stage_key)
    if stage is None:
        raise KeyError(stage_key)
    return [f"{REQUIREMENTS[r]['label']} — {REQUIREMENTS[r]['supply']}"
            for r in stage.needs if not _has(db, session_id, r)]
