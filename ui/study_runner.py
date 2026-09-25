"""
The post-question stages for sessions whose brief declares a dataset:
S2 data audit → S3 hypotheses (user selects) → S4 analysis plan (user approves)
→ S5 assembly → S6 analysis run → S7 results table → S8 claims and report →
S9 review. See the design document for the supervisor-gate redesign (2026-09-14).

Every stage stores a versioned document (NoteDB.save_artifact). A stage is
skipped on resume only when its document passed and was built from the
current version of the document before it; anything that fails or is blocked
stops the pipeline with the reason shown. Nothing here falls back to the old
ML-template stages.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)


class StudyStopped(Exception):
    """The user stopped the session while it was waiting or running."""


def _digest(content) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


# --- gate decisions, usable without a running pipeline -------------------------------
# A gate answer used to be delivered only to a waiting thread, so after a server
# restart the stored document still said "awaiting approval" while the buttons
# that answer it were gone (2026-09-20 product audit).

def apply_hypothesis_selection(db, session_id: str, ids: list[str]) -> tuple[bool, str]:
    """Store the user's hypothesis choice. Returns (accepted, message)."""
    art = db.get_artifact(session_id, "hypotheses")
    if art is None or art["status"] not in ("awaiting_approval", "passed"):
        return False, "This session has no hypotheses to choose from."
    testable = {h["id"] for h in art["content"]["hypotheses"] if h["testable"]}
    chosen = list(dict.fromkeys(ids or []))
    unknown = [i for i in chosen if i not in testable]
    if not chosen or unknown:
        return False, f"Choose one or more testable hypotheses (not {', '.join(unknown) or 'none'})."
    by_id = {h["id"]: h for h in art["content"]["hypotheses"]}
    db_ids = dict(art["content"].get("db_ids") or {})
    for hid in chosen:
        if hid not in db_ids:
            db_ids[hid] = db.save_hypothesis(session_id, by_id[hid]["statement"],
                                             experiment_design={"operationalization": by_id[hid]["rows"]})
            db.update_hypothesis_status(db_ids[hid], "selected", domain="study (declared dataset)")
    version = db.save_artifact(session_id, "hypotheses",
                               art["content"] | {"selected": chosen, "db_ids": db_ids}, "passed")
    db.approve_artifact(session_id, "hypotheses", version)
    db.update_session(session_id, status="hypotheses_selected")
    return True, f"Studying {', '.join(chosen)}."


def apply_source_decision(db, session_id: str, proceed: bool) -> tuple[bool, str]:
    """
    Store what the user decided about a source the brief relies on that is
    blocked. Returns (proceeding, message).
    """
    art = db.get_artifact(session_id, "source_check")
    if art is None or art["status"] not in ("awaiting_approval", "passed"):
        return False, "This session is not waiting on a source decision."
    content = art["content"] | {"decision": "proceed" if proceed else "stop"}
    if proceed:
        version = db.save_artifact(session_id, "source_check", content, "passed")
        db.approve_artifact(session_id, "source_check", version)
        return True, "Continuing without the blocked source; it is recorded as a limitation."
    db.save_artifact(session_id, "source_check", content, "blocked")
    return False, "Stopped: the study waits until the source the brief relies on is usable."


def apply_plan(db, session_id: str, text: str, approve: bool) -> tuple[bool, list[str]]:
    """Check the plan text and store it; approve it when it has no problems. Returns (approved, problems)."""
    from agents.analysis_plan import parse_plan, validate_plan

    audit = db.get_artifact(session_id, "data_audit")
    hyp = db.get_artifact(session_id, "hypotheses")
    if audit is None or hyp is None or not hyp["content"].get("selected"):
        return False, ["This session has no approved hypotheses yet."]
    selected = {h["id"]: h for h in hyp["content"]["hypotheses"] if h["id"] in hyp["content"]["selected"]}
    tests = validate_plan(parse_plan(text or ""), selected, audit["content"])
    problems = [f"{t['id']}: {p}" for t in tests for p in t["problems"]]
    if not tests:
        problems.append("The plan has no TEST blocks.")
    content = {"hypotheses_version": hyp["version"], "tests": tests, "text": text or "", "problems": len(problems)}
    if approve and not problems:
        version = db.save_artifact(session_id, "plan", content, "passed")
        db.approve_artifact(session_id, "plan", version)
        db.update_session(session_id, status="plan_approved")
        return True, []
    db.save_artifact(session_id, "plan", content, "awaiting_approval")
    return False, problems


# Documents to invalidate when a stage is redone: the stage itself and everything
# built from it, so a rerun cannot mix old and new.
DOWNSTREAM = {
    "hypotheses": ["hypotheses", "plan", "study_protocol", "intent_fidelity",
                   "methodology_review", "build_manifest", "scientific_conformance",
                   "software_preflight", "verified_ready", "assembly", "run", "results",
                   "result_conformance", "claims", "report", "review"],
    "plan": ["plan", "study_protocol", "intent_fidelity", "methodology_review",
             "build_manifest", "scientific_conformance", "software_preflight",
             "verified_ready", "assembly", "run", "results", "result_conformance",
             "claims", "report", "review"],
    "analysis": ["verified_ready", "run", "results", "result_conformance",
                 "claims", "report", "review"],
    "report": ["claims", "report", "review"],
    "review": ["review"],
}


def invalidate(db, session_id: str, stage: str, note: str = "redo requested") -> list[str]:
    """Mark a stage and its dependents as failed so the pipeline rebuilds them."""
    import shutil
    if stage not in DOWNSTREAM:
        raise ValueError(f"unknown stage {stage!r}")
    done = []
    for name in DOWNSTREAM[stage]:
        art = db.get_artifact(session_id, name)
        if art is not None and art["status"] != "failed":
            db.save_artifact(session_id, name, art["content"], "failed", note=note)
            done.append(name)
    if stage == "analysis":
        results = config.session_experiment_dir(session_id) / "results"
        if results.exists():
            shutil.rmtree(results)
    status = {"hypotheses": "data_audited", "plan": "hypotheses_selected", "analysis": "plan_approved",
              "report": "experiment_run", "review": "report_written"}[stage]
    db.update_session(session_id, status=status)
    return done


class StudyPipeline:
    def __init__(self, runner, note_db, api_model, declared) -> None:
        self.r = runner
        self.db = note_db
        self.api = api_model
        self.sid = runner.session_id
        self.url, self.schema, self.path = declared
        from agents.degradation import DegradationLog
        self.deg = DegradationLog(note_db, self.sid, notify=lambda m: runner.emit("log", {"message": m}))

    # --- helpers ---------------------------------------------------------------
    def _current(self, stage: str, upstream_key: str | None = None, upstream_value=None) -> dict | None:
        art = self.db.get_artifact(self.sid, stage)
        if art is None or art["status"] != "passed":
            return None
        if upstream_key and art["content"].get(upstream_key) != upstream_value:
            return None
        return art

    def _stage(self, phase: int, name: str) -> None:
        if self.r._stop_flag.is_set():
            raise StudyStopped()
        self.r.emit("phase_start", {"phase": phase, "name": name})

    def _fail(self, stage: str, message: str) -> bool:
        self.r.emit("study_blocked", {"stage": stage, "message": message})
        self.r.emit("error", {"message": f"{stage}: {message}"})
        return False

    # --- run -------------------------------------------------------------------
    def _stop_here(self, stage: str) -> bool:
        """
        True when the caller asked for this one stage only. Someone who has
        already done the earlier work runs a single stage (agents/stages.py);
        the stages before it are still checked, but skipped if already passed.
        """
        only = getattr(self.r, "only", None)
        if only != stage:
            return False
        self.r.emit("stage_done", {"stage": stage})
        self.r.emit("log", {"message": f"Stage '{stage}' finished; stopping here as asked."})
        return True

    def run(self) -> bool:
        session = self.db.get_session(self.sid)
        question = session.get("research_question") or ""
        papers = self.db.get_papers(self.sid)

        if not self._check_required_sources(session):
            return False
        audit_art = self._audit(question)
        if audit_art is None:
            return False
        if self._stop_here("audit"):
            return True
        hyp_art = self._hypotheses(question, session, audit_art, papers)
        if hyp_art is None:
            return False
        if self._stop_here("hypotheses"):
            return True
        plan_art = self._plan(audit_art, hyp_art)
        if plan_art is None:
            return False
        if self._stop_here("plan"):
            return True
        run = self._run_analysis(audit_art, hyp_art, plan_art)
        if run is None:
            return False
        table_art = self._results(plan_art, hyp_art, run)
        if table_art is None:
            return False
        if self._stop_here("analysis"):
            return True
        claims_art, report_art = self._report(session, audit_art, hyp_art, plan_art, table_art, papers)
        if self._stop_here("report"):
            return True
        self._review(question, hyp_art, plan_art, table_art, claims_art, report_art)
        self.db.update_session(self.sid, status="reviewed")
        return True

    # --- S2 --------------------------------------------------------------------
    def _blocked_required_sources(self, session: dict) -> list[str]:
        """Sources the brief says to rely on that are currently blocked."""
        from datetime import datetime, timezone

        from tools.rate_limit import get_limiter
        brief = " ".join(str(session.get(k) or "") for k in ("background", "goals", "constraints")).lower()
        limiter = get_limiter()
        problems = []
        for source, name in (("semantic_scholar", "semantic scholar"), ("arxiv", "arxiv"),
                             ("openalex", "openalex"), ("europepmc", "europe pmc"), ("crossref", "crossref")):
            until = limiter.blocked_until(source)
            if name in brief and until:
                when = datetime.fromtimestamp(until, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                problems.append(f"The brief asks to rely on {name}, but that source is blocked until {when}. "
                                "The collection did not use it.")
        return problems

    def _check_required_sources(self, session: dict) -> bool:
        """
        The brief may tell the pipeline to rely on a source (2026-09-13 brief:
        "Rely on the Semantic Scholar canon seeding path"). If that source is
        blocked, the study is not silently run on a different paper set: the
        user decides whether to go on without it, and going on is recorded as a
        limitation. Returns False when the study should stop.
        """
        problems = self._blocked_required_sources(session)
        art = self.db.get_artifact(self.sid, "source_check")
        if not problems:
            return True
        if art is None or art["content"].get("problems") != problems or art["status"] == "failed":
            self.db.save_artifact(self.sid, "source_check", {"problems": problems}, "awaiting_approval")
            art = self.db.get_artifact(self.sid, "source_check")
        if art["status"] == "blocked":
            self._fail("Source check", art["content"]["problems"][0])
            return False
        if not (art["status"] == "passed" and art["approved"]):
            self.r.emit("source_check", art["content"] | {"status": art["status"]})
            while True:
                reply = self.r.wait_for_input(
                    "source_confirmation",
                    "A source the brief relies on is blocked. Continue without it, or stop?") or {}
                proceeding, message = apply_source_decision(self.db, self.sid, bool(reply.get("proceed")))
                self.r.emit("log", {"message": message})
                if proceeding:
                    break
                self.r.emit("source_check", self.db.get_artifact(self.sid, "source_check")["content"]
                            | {"status": "blocked"})
                self._fail("Source check", message)
                return False
        for problem in problems:
            self.deg.record(1, "required_source", "critical", problem)
        return True

    def _audit(self, question: str) -> dict | None:
        from agents.data_audit import DataAuditError, build_audit
        self._stage(4, "Data audit")
        art = self._current("data_audit")
        if art is None or art["content"]["question"].get("text") != question:
            q_art = self.db.get_artifact(self.sid, "question")
            q = q_art["content"] if q_art else {"text": question}
            try:
                audit = build_audit(self.schema, self.path, q)
            except DataAuditError as exc:
                self.db.save_artifact(self.sid, "data_audit", {"question": q, "error": str(exc)}, "blocked")
                self._fail("Data audit", str(exc))
                return None
            self.db.save_artifact(self.sid, "data_audit", audit, "passed")
            art = self.db.get_artifact(self.sid, "data_audit")
        self.r.emit("data_audit", art["content"])
        self.db.update_session(self.sid, status="data_audited")
        return art

    # --- S3 --------------------------------------------------------------------
    def _embedder(self):
        try:
            from models.ollama_model import OllamaEmbedModel
            emb = OllamaEmbedModel()
            emb.load()
            return emb
        except Exception as exc:
            logger.warning("No embedding model for hypothesis checks: %s", exc)
            return None

    def _hypotheses(self, question, session, audit_art, papers) -> dict | None:
        from agents.data_audit import describe_for_prompt
        from agents.hypothesis_design import HypothesisDesigner
        self._stage(4, "Hypotheses")
        art = self.db.get_artifact(self.sid, "hypotheses")
        fresh = (art is None or art["content"].get("audit_version") != audit_art["version"]
                 or art["status"] == "failed")
        if fresh:
            designer = HypothesisDesigner(self.api, self._embedder(), self.deg)
            hyps, raw = designer.generate(question, session, describe_for_prompt(audit_art["content"]), papers)
            hyps = designer.check(hyps, audit_art["content"], papers)
            content = {"audit_version": audit_art["version"], "question": question, "hypotheses": hyps,
                       "selected": [], "raw": raw}
            status = "awaiting_approval" if any(h["testable"] for h in hyps) else "blocked"
            self.db.save_artifact(self.sid, "hypotheses", content, status)
            art = self.db.get_artifact(self.sid, "hypotheses")
        self.r.emit("hypothesis_candidates", art["content"] | {"status": art["status"]})
        if art["status"] == "blocked":
            reason = ("no hypothesis could be written" if not art["content"]["hypotheses"] else
                      "no hypothesis maps to variables in the data; see each hypothesis' problems")
            return self._fail("Hypotheses", reason + ". Revise the research question or the brief and resume.") or None
        if art["status"] == "passed" and art["approved"]:
            return art

        while True:
            ids = self.r.wait_for_input("hypothesis_selection",
                                        "Select the hypotheses to study (only testable ones can be selected).")
            accepted, message = apply_hypothesis_selection(self.db, self.sid, ids)
            self.r.emit("log", {"message": message})
            if accepted:
                break
        art = self.db.get_artifact(self.sid, "hypotheses")
        self.r.emit("hypothesis_candidates", art["content"] | {"status": art["status"]})
        return art

    # --- S4 --------------------------------------------------------------------
    def _plan(self, audit_art, hyp_art) -> dict | None:
        from agents.analysis_plan import PlanWriter, parse_plan, render_plan, validate_plan
        self._stage(5, "Analysis plan")
        audit = audit_art["content"]
        selected = {h["id"]: h for h in hyp_art["content"]["hypotheses"] if h["id"] in hyp_art["content"]["selected"]}
        art = self.db.get_artifact(self.sid, "plan")
        if (art is None or art["status"] == "failed"
                or art["content"].get("hypotheses_version") != hyp_art["version"]):
            writer = PlanWriter(self.api)
            tests = []
            for h in selected.values():
                tests += writer.write(h, audit)
            content = {"hypotheses_version": hyp_art["version"], "tests": tests, "text": render_plan(tests),
                       "problems": sum((len(t["problems"]) for t in tests), 0)}
            self.db.save_artifact(self.sid, "plan", content, "awaiting_approval")
            art = self.db.get_artifact(self.sid, "plan")
        if art["status"] == "passed" and art["approved"]:
            self.r.emit("analysis_plan", art["content"] | {"status": "passed", "approved": True})
            return art

        while True:
            self.r.emit("analysis_plan", art["content"] | {"status": art["status"], "approved": False})
            reply = self.r.wait_for_input("plan_approval",
                                          "Review the analysis plan. Edit it if needed, then approve it.") or {}
            approved, problems = apply_plan(self.db, self.sid, reply.get("text", ""), bool(reply.get("approve")))
            for problem in problems:
                self.r.emit("log", {"message": problem})
            art = self.db.get_artifact(self.sid, "plan")
            if approved:
                self.r.emit("analysis_plan", art["content"] | {"status": "passed", "approved": True})
                return art
            if reply.get("approve"):
                self.r.emit("log", {"message": "The plan cannot be approved while tests have problems."})

    # --- S5 + S6 ---------------------------------------------------------------
    def _run_analysis(self, audit_art, hyp_art, plan_art) -> dict | None:
        from agents.experiment_runner import ExperimentRunnerAgent
        from agents.control_boundary import prepare_declared_dataset
        self._stage(6, "Analysis")
        session = self.db.get_session(self.sid)
        folder = config.session_experiment_dir(self.sid)
        outcome = prepare_declared_dataset(
            self.sid, self.db, folder, session.get("research_question") or "",
            hyp_art["content"], audit_art["content"], plan_art["content"]["tests"],
            plan_art["version"], self.path)
        for stage, artifact in (("Intent Fidelity", "intent_fidelity"),
                                ("Methodology Review", "methodology_review"),
                                ("Scientific Conformance", "scientific_conformance"),
                                ("Software Preflight", "software_preflight")):
            record = self.db.get_artifact(self.sid, artifact)
            if record is not None:
                self.r.emit("control_gate", {"stage": stage, "status": record["status"],
                                             "content": record["content"]})
        if not outcome.ready:
            stage = {
                "intent_fidelity_failed": "Intent Fidelity",
                "design_needs_human": "Intent Fidelity / Methodology Review",
                "design_rejected": "Methodology Review",
                "scientific_verification_failed": "Scientific Conformance",
                "software_verification_failed": "Software Preflight",
            }.get(outcome.status.value, "Study control")
            return self._fail(stage, outcome.notes[0] if outcome.notes else outcome.status.value) or None

        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.db.save_artifact(self.sid, "assembly", manifest | {"plan_version": plan_art["version"]}, "passed")
        self.db.update_session(self.sid, status="code_generated")
        self.r.emit("analysis_files", {"folder": str(config.session_experiment_dir(self.sid)),
                                       "files": sorted(manifest["files"]), "code_hash": manifest["code_hash"]})

        runner = ExperimentRunnerAgent(api_model=self.api, note_db=self.db,
                                       experiments_base_dir=config.EXPERIMENTS_DIR)
        first_id = next(iter(hyp_art["content"]["db_ids"].values()))
        result = runner.run_manifest(self.sid, config.session_experiment_dir(self.sid), first_id)
        content = result | {"plan_version": plan_art["version"]}
        self.db.save_artifact(self.sid, "run", content, result["status"])
        self.r.emit("analysis_run", content)
        if result["status"] != "passed":
            return self._fail(result.get("failure_stage", "Analysis"),
                              "; ".join(result["problems"]) or
                              "the analysis did not finish") or None
        self.db.update_session(self.sid, status="experiment_run")
        return self.db.get_artifact(self.sid, "run")

    # --- S7 --------------------------------------------------------------------
    def _results(self, plan_art, hyp_art, run_art) -> dict | None:
        from agents import scientific_conformance
        from agents import results_table
        self._stage(7, "Results")
        folder = config.session_experiment_dir(self.sid)
        result_check = scientific_conformance.verify_results(folder)
        self.db.save_artifact(self.sid, "result_conformance", result_check.as_dict(),
                              "passed" if result_check.passed else "blocked")
        self.r.emit("control_gate", {"stage": "Result Conformance",
                                     "status": "passed" if result_check.passed else "blocked",
                                     "content": result_check.as_dict()})
        if not result_check.passed:
            return self._fail("Result Conformance", result_check.summary()) or None
        table = results_table.build(plan_art["content"], hyp_art["content"],
                                    folder, self.db.get_degradations(self.sid))
        table["run_code_hash"] = run_art["content"]["code_hash"]
        art = self._current("results")
        if art is None or _digest(art["content"]) != _digest(table):
            self.db.save_artifact(self.sid, "results", table, "passed")
            art = self.db.get_artifact(self.sid, "results")
        self.r.emit("results_table", art["content"])
        return art

    # --- S8 --------------------------------------------------------------------
    def _report(self, session, audit_art, hyp_art, plan_art, table_art, papers):
        from agents.claims_report import ClaimsReportWriter
        from ui.report_renderer import save_all
        self._stage(8, "Report")
        claims_art = self._current("claims", "results_hash", table_art["content_hash"])
        report_art = self._current("report", "results_hash", table_art["content_hash"])
        writer = ClaimsReportWriter(self.api, self.deg)
        if claims_art is None or report_art is None:
            audit = audit_art["content"]
            meanings = {c["code"]: c["meaning"] for i in audit["indicators"] for codes in i["splits"].values()
                        for c in codes}
            meanings.update({g["code"]: g["meaning"] for codes in audit["groups"].values() for g in codes})
            claims = writer.claims(session.get("research_question") or "", table_art["content"],
                                   plan_art["content"], meanings)
            self.db.save_artifact(self.sid, "claims", claims | {"results_hash": table_art["content_hash"]}, "passed")
            claims_art = self.db.get_artifact(self.sid, "claims")
            run_art = self.db.get_artifact(self.sid, "run")
            notebook = config.session_experiment_dir(self.sid) / "notebook.jsonl"
            entries = [json.loads(l) for l in notebook.read_text(encoding="utf-8").splitlines()] \
                if notebook.exists() else []
            provenance = {"session_id": self.sid,
                          "code_hash": (run_art or {}).get("content", {}).get("code_hash"),
                          "run_at": entries[-1]["time"] if entries else "?",
                          "plan_version": plan_art["version"]}
            report = writer.report(self.db.get_session(self.sid), audit_art["content"], hyp_art["content"],
                                   plan_art["content"], table_art["content"], claims, papers, provenance)
            self.db.save_artifact(self.sid, "report", report | {"results_hash": table_art["content_hash"]}, "passed")
            report_art = self.db.get_artifact(self.sid, "report")
        report = {k: v for k, v in report_art["content"].items() if k != "results_hash"}
        out_dir = Path(config.BASE_DIR) / "data" / "reports" / self.sid
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        save_all(report, out_dir)
        self.db.update_session(self.sid, report=json.dumps(report, ensure_ascii=False), status="report_written")
        self.r.emit("claims", claims_art["content"])
        self.r.emit("report", report)
        return claims_art, report_art

    # --- S9 --------------------------------------------------------------------
    def _review(self, question, hyp_art, plan_art, table_art, claims_art, report_art) -> None:
        from agents.claims_report import format_table
        from agents.plan_review import model_issues, review
        self._stage(8, "Review")
        # Keyed on the claims, not the report: the review is written into the
        # report below, which would otherwise invalidate it on every resume.
        art = self._current("review", "claims_hash", claims_art["content_hash"])
        if art is None:
            findings = review(hyp_art["content"], plan_art["content"], table_art["content"], claims_art["content"],
                              report_art["content"])
            ids = {r["id"] for r in table_art["content"]["rows"]} | {c["id"] for c in claims_art["content"]["accepted"]}
            findings += model_issues(self.api, question, format_table(table_art["content"]), claims_art["content"],
                                     ids, self.deg)
            self.db.save_artifact(self.sid, "review", {"findings": findings, "claims_hash": claims_art["content_hash"]},
                                  "passed")
            art = self.db.get_artifact(self.sid, "review")
        self._attach_review_to_report(report_art, art)
        self.r.emit("study_review", art["content"])
        self.r.emit("phase_done", {"phase": 8, "name": "Report and review"})

    def _attach_review_to_report(self, report_art, review_art) -> None:
        """The review belongs in the document, not only on screen."""
        from ui.report_renderer import save_all
        findings = review_art["content"]["findings"]
        text = "\n".join(f"- [{f['level']}] {f['detail']}" for f in findings) or "No review findings."
        report = {k: v for k, v in report_art["content"].items() if k != "results_hash"}
        if report.get("review") == text:
            return
        report["review"] = text
        self.db.save_artifact(self.sid, "report", report | {"results_hash": report_art["content"].get("results_hash")},
                              "passed")
        out_dir = Path(config.BASE_DIR) / "data" / "reports" / self.sid
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        save_all(report, out_dir)
        self.db.update_session(self.sid, report=json.dumps(report, ensure_ascii=False))
        self.r.emit("report", report)
