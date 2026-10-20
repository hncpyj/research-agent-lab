"""
Filing a run so it can be used as evidence later.

A result that lives only in a terminal scrollback is not evidence. This writes
each meaningful run three times, on purpose:

    research_logs/runs/<stamp>_<summary>.md       for a person to read
    research_logs/records/<stamp>_<summary>.json  for a table to be computed from
    research_logs/runs.jsonl                      one line, for aggregation

Nothing here overwrites an earlier record. The filename carries a sortable
local timestamp; the record carries the timezone-aware one, the commit, and
whether the tree was dirty, because "which code produced this" is the first
question anyone will ask of a number.

The Markdown template is fixed. A section left empty is a section that was not
thought about, and it shows.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = "run_record_v1"
ROOT = Path(__file__).parent.parent / "research_logs"
RUNS, RECORDS, JSONL = ROOT / "runs", ROOT / "records", ROOT / "runs.jsonl"

EVALUATION_KINDS = ("DEVELOPMENT", "PILOT", "CONFIRMATORY")
CLASSIFICATIONS = ("A", "B", "C", "D")
DECISIONS = ("KEEP", "REVISE", "REVERT", "INCONCLUSIVE")


def git_state() -> tuple[str, bool]:
    """The commit this ran at, and whether the tree had uncommitted changes."""
    root = Path(__file__).parent.parent
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                                capture_output=True, text=True, timeout=30).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root,
                                    capture_output=True, text=True,
                                    timeout=30).stdout.strip())
        return commit or "unknown", dirty
    except Exception:
        return "unknown", True


def environment() -> dict:
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.node()}


@dataclass
class RunRecord:
    """One run, with the fields a later table will need."""

    summary: str                       # at most three words, used in the filename
    title: str
    question: str
    change: str
    prediction: str
    baseline: str
    procedure: str
    classification: str                # A | B | C | D
    evaluation_kind: str               # DEVELOPMENT | PILOT | CONFIRMATORY
    decision: str                      # KEEP | REVISE | REVERT | INCONCLUSIVE
    next_test: str

    benchmark_version: str = "none"
    benchmark_cases: list = field(default_factory=list)
    protocol_version: str | int | None = None
    protocol_hash: str | None = None
    build_manifest_hash: str | None = None
    # Intent fidelity is recorded separately from the methodology verdict and
    # never combined with it: they answer different questions and either can
    # pass while the other fails.
    intent_fidelity_status: str | None = None
    intent_fidelity_findings_count: int = 0
    intent_fidelity_failure_codes: list = field(default_factory=list)
    intent_fidelity_needs_human_count: int = 0
    methodology_status: str | None = None
    previous_protocol_hash: str | None = None
    reason_for_protocol_change: str | None = None
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    generation_config: dict = field(default_factory=dict)
    seeds: list = field(default_factory=list)
    test_layers_run: list = field(default_factory=list)

    metrics: dict = field(default_factory=dict)
    qualitative: str = ""
    failure_events: list = field(default_factory=list)   # {"label":…, "detail":…, …}
    comparison: str = ""
    interpretation: str = ""
    threats: str = ""
    paper_claim_ids: list = field(default_factory=list)
    baseline_run_ids: list = field(default_factory=list)
    artifact_hashes: dict = field(default_factory=dict)
    raw_record_paths: list = field(default_factory=list)
    unproven: str = ""
    notes: str = ""

    def __post_init__(self):
        if self.classification not in CLASSIFICATIONS:
            raise ValueError(f"classification must be one of {CLASSIFICATIONS}")
        if self.evaluation_kind not in EVALUATION_KINDS:
            raise ValueError(f"evaluation_kind must be one of {EVALUATION_KINDS}")
        if self.decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        words = len(self.summary.split("_"))
        if words > 3:
            raise ValueError("the summary is at most three words, joined by underscores")

    # ------------------------------------------------------------------
    @property
    def taxonomy_counts(self) -> dict:
        counts: dict[str, int] = {}
        for event in self.failure_events:
            for label in event.get("labels", []) or ([event["label"]] if event.get("label") else []):
                counts[label] = counts.get(label, 0) + 1
        return dict(sorted(counts.items()))

    def write(self, when: datetime | None = None) -> tuple[Path, Path]:
        """File this run. Returns (markdown path, json path)."""
        when = when or datetime.now().astimezone()
        stamp = when.strftime("%Y%m%d_%H%M")
        commit, dirty = git_state()
        run_id = f"{stamp}_{self.summary}"

        RUNS.mkdir(parents=True, exist_ok=True)
        RECORDS.mkdir(parents=True, exist_ok=True)
        markdown = RUNS / f"{run_id}.md"
        record = RECORDS / f"{run_id}.json"
        if markdown.exists() or record.exists():
            # Never overwrite: a second run in the same minute gets its own file.
            run_id = f"{run_id}_{when.strftime('%S')}"
            markdown = RUNS / f"{run_id}.md"
            record = RECORDS / f"{run_id}.json"

        markdown.write_text(self._markdown(run_id, when, commit, dirty), encoding="utf-8")
        payload = self._json(run_id, when, commit, dirty)
        record.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        with JSONL.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._compact(payload), ensure_ascii=False) + "\n")
        return markdown, record

    # ------------------------------------------------------------------
    def _json(self, run_id: str, when: datetime, commit: str, dirty: bool) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "run_id": run_id,
            "timestamp": when.isoformat(timespec="seconds"),
            "summary": self.summary,
            "title": self.title,
            "git_commit": commit,
            "working_tree_dirty": dirty,
            "research_classification": self.classification,
            "evaluation_kind": self.evaluation_kind,
            "benchmark_version": self.benchmark_version,
            "benchmark_cases": self.benchmark_cases,
            "protocol_version": self.protocol_version,
            "protocol_hash": self.protocol_hash,
            "previous_protocol_hash": self.previous_protocol_hash,
            "reason_for_protocol_change": self.reason_for_protocol_change,
            "build_manifest_hash": self.build_manifest_hash,
            "intent_fidelity_status": self.intent_fidelity_status,
            "intent_fidelity_findings_count": self.intent_fidelity_findings_count,
            "intent_fidelity_failure_codes": self.intent_fidelity_failure_codes,
            "intent_fidelity_needs_human_count": self.intent_fidelity_needs_human_count,
            "methodology_status": self.methodology_status,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "generation_config": self.generation_config,
            "seeds": self.seeds,
            "change_description": self.change,
            "prediction": self.prediction,
            "baseline": self.baseline,
            "baseline_run_ids": self.baseline_run_ids,
            "test_layers_run": self.test_layers_run,
            "metrics": self.metrics,
            "failure_events": self.failure_events,
            "failure_taxonomy_counts": self.taxonomy_counts,
            "artifact_hashes": self.artifact_hashes,
            "raw_record_paths": self.raw_record_paths,
            "decision": self.decision,
            "next_test": self.next_test,
            "paper_claim_ids": self.paper_claim_ids,
            "environment": environment(),
            "notes": self.notes,
        }

    def _compact(self, payload: dict) -> dict:
        return {k: payload[k] for k in (
            "run_id", "timestamp", "summary", "git_commit", "working_tree_dirty",
            "research_classification", "evaluation_kind", "benchmark_version",
            "protocol_hash", "previous_protocol_hash", "intent_fidelity_status",
            "intent_fidelity_failure_codes", "methodology_status",
            "model", "test_layers_run", "metrics",
            "failure_taxonomy_counts", "decision", "paper_claim_ids")}

    def _markdown(self, run_id: str, when: datetime, commit: str, dirty: bool) -> str:
        def table(metrics: dict) -> str:
            if not metrics:
                return "_none recorded_"
            rows = ["| Metric | Value |", "|---|---|"]
            for key, value in metrics.items():
                rows.append(f"| {key} | {value} |")
            return "\n".join(rows)

        failures = "_none_"
        if self.failure_events:
            rows = ["| Labels | What happened | Detected at | Would have invalidated? |",
                    "|---|---|---|---|"]
            for event in self.failure_events:
                labels = ", ".join(event.get("labels", []) or [event.get("label", "UNKNOWN")])
                rows.append(f"| `{labels}` | {event.get('detail', '')} | "
                            f"{event.get('detected_at', 'not detected')} | "
                            f"{event.get('would_invalidate', 'unknown')} |")
            failures = "\n".join(rows)

        counts = self.taxonomy_counts
        counts_text = ", ".join(f"`{k}` × {v}" for k, v in counts.items()) or "_none_"

        return f"""# {self.title}

Timestamp: {when.isoformat(timespec="seconds")}
Git commit: `{commit}`
Working-tree status: {"dirty (uncommitted changes present)" if dirty else "clean"}
Research classification: {self.classification}
Evaluation kind: {self.evaluation_kind}
Benchmark version: {self.benchmark_version}
Benchmark cases: {", ".join(self.benchmark_cases) or "none"}
Protocol version/hash: {self.protocol_version} / `{self.protocol_hash}`
Previous protocol hash: {f'`{self.previous_protocol_hash}`' if self.previous_protocol_hash else "unchanged"}
Reason for protocol change: {self.reason_for_protocol_change or "n/a"}
Intent fidelity: {self.intent_fidelity_status or "not run"} ({self.intent_fidelity_findings_count} findings, {self.intent_fidelity_needs_human_count} needing a human; codes: {", ".join(self.intent_fidelity_failure_codes) or "none"})
Methodology review: {self.methodology_status or "not run"}
BuildManifest hash: `{self.build_manifest_hash}`
Model/provider: {self.model or "n/a"} / {self.provider or "n/a"}
Model version: {self.model_version or "not_available"}
Generation settings: {json.dumps(self.generation_config) if self.generation_config else "n/a"}
Seed(s): {", ".join(str(s) for s in self.seeds) or "n/a"}
Environment: {environment()["python"]} on {environment()["platform"]}
Test layers run: {", ".join(self.test_layers_run) or "none"}

## Question

{self.question}

## Change

{self.change}

## Prediction

{self.prediction}

## Baseline

{self.baseline}

## Test Procedure

{self.procedure}

## Quantitative Results

{table(self.metrics)}

## Qualitative Results

{self.qualitative or "_none recorded_"}

## Failures

{failures}

Taxonomy counts: {counts_text}

## Comparison to Baseline

{self.comparison or "_no comparison made_"}

## Interpretation

{self.interpretation or "_none_"}

## Threats / Confounds

{self.threats or "_none identified — which is itself a threat_"}

## What remains unproven

{self.unproven or "_not stated_"}

## Decision

{self.decision}

## Next Test

{self.next_test}

## Paper Relevance

{", ".join(self.paper_claim_ids) or "none yet"}

## Raw records

{chr(10).join(f"- `{p}`" for p in self.raw_record_paths) or "_none_"}

Artifact hashes: {json.dumps(self.artifact_hashes) if self.artifact_hashes else "_none_"}

{self.notes}
"""


def load_runs() -> list[dict]:
    """Every run recorded so far, for a synthesis or an aggregate table."""
    if not JSONL.exists():
        return []
    return [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def benchmark(version: str = "v1") -> dict:
    path = ROOT / "benchmark" / f"benchmark_{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"no benchmark {version}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
