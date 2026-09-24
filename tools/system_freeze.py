"""
The system under test, named and hashed, before any fault is injected.

A safety evaluation whose subject moved during the run measures nothing. So
every component that could decide a verdict is hashed first and the hashes are
written into the evaluation's own record; the run re-reads them at the end and
says whether anything moved.

Some components have no version constant of their own -- preflight and result
conformance are modules, not versioned artifacts. Their file hash is recorded
in place of a version, and that absence is itself reported rather than papered
over with a number invented here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

# component -> (file, what it decides)
COMPONENTS = {
    "intent_fidelity": ("agents/intent_fidelity.py",
                        "is this the study that was approved (pre-freeze)"),
    "scientific_concepts": ("agents/scientific_concepts.py",
                            "the identity of each scientific thing"),
    "methodology_review": ("agents/methodology_review.py",
                           "is the design sound (pre-freeze)"),
    "study_protocol": ("agents/study_protocol.py", "the scientific contract and its hash"),
    "build_manifest": ("agents/build_manifest.py", "how the study is to be implemented"),
    "study_builder": ("agents/study_builder.py", "the order of the gates"),
    "scientific_conformance": ("agents/scientific_conformance.py",
                               "do the artifacts and the results match the frozen protocol"),
    "software_preflight": ("agents/preflight.py",
                           "does the software compile, import, and run once"),
    "controlled_llm_scaffold": ("agents/controlled_llm_scaffold.py",
                                "the deterministic apparatus and what a model may write"),
    "choice_set_apparatus": ("tools/choice_set.py",
                             "the trusted rules: pool integrity, curation limits, logging"),
}

VERSIONED = {
    "study_protocol_schema": "PROTOCOL_FILE + _SCIENTIFIC_FIELDS (no explicit version constant)",
    "software_preflight_version": "none declared; file hash stands in",
    "result_conformance_version": ("none declared; it is "
                                   "scientific_conformance.verify_results, and the file "
                                   "hash stands in"),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def git_commit() -> tuple[str, bool]:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, timeout=20).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                    capture_output=True, text=True,
                                    timeout=20).stdout.strip())
        return commit, dirty
    except Exception:
        return "", True


def snapshot(benchmark_version: str, protocol_hash: str = "",
             manifest_hash: str = "") -> dict:
    """Everything that could change a verdict, hashed."""
    commit, dirty = git_commit()
    return {
        "frozen_at_commit": commit,
        "working_tree_dirty": dirty,
        "benchmark_version": benchmark_version,
        "protocol_hash": protocol_hash,
        "build_manifest_hash": manifest_hash,
        "component_hashes": {name: _sha(ROOT / path)
                             for name, (path, _) in COMPONENTS.items()},
        "component_roles": {name: role for name, (_, role) in COMPONENTS.items()},
        "declared_versions": VERSIONED,
    }


def drift(before: dict) -> dict:
    """Which components moved since the snapshot. Empty means none did."""
    now = {name: _sha(ROOT / path) for name, (path, _) in COMPONENTS.items()}
    return {name: {"before": before["component_hashes"][name], "after": value}
            for name, value in now.items()
            if before["component_hashes"].get(name) != value}


if __name__ == "__main__":
    print(json.dumps(snapshot("v3"), indent=1))
