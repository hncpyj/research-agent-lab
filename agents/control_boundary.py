"""Shared production control boundary and hash-bound execution permission.

The scientific rules remain in intent_fidelity, methodology_review, and
scientific_conformance; software rules remain in preflight.  This module only
orders them, persists their separate outcomes, and turns two passing build
gates into a package-specific execution receipt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from agents.build_manifest import BuildManifest, Status, file_hash
from agents.study_protocol import StudyProtocol

READY_FILE = "verified_ready.json"
READY_VERSION = 1


class ControlBoundaryBlocked(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


@dataclass
class ControlOutcome:
    status: Status
    protocol: StudyProtocol | None = None
    manifest: BuildManifest | None = None
    fidelity: object | None = None
    methodology: object | None = None
    conformance: object | None = None
    preflight: object | None = None
    receipt: dict | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status is Status.VERIFIED_READY


def _canonical_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                   default=str).encode()
    ).hexdigest()


def package_fingerprint(folder: Path | str, protocol: StudyProtocol,
                        manifest: BuildManifest) -> str:
    """Identity of every executable/contract artifact the manifest names."""
    folder = Path(folder)
    names = ([artifact.path for artifact in manifest.trusted_artifacts]
             + [artifact.path for artifact in manifest.generated_artifacts]
             + list(manifest.deterministic_artifacts)
             + list(manifest.entrypoints.values()))
    # An unlisted Python file can still be imported by an entrypoint. Bind it
    # too, so adding executable code invalidates permission rather than hiding
    # outside the manifest's declared set.
    names.extend(str(path.relative_to(folder)).replace("\\", "/")
                 for path in folder.rglob("*.py")
                 if not ({"results", "__pycache__"} & set(path.relative_to(folder).parts)))
    files = {}
    for name in dict.fromkeys(n for n in names if n):
        path = folder / name
        files[name] = file_hash(path) if path.is_file() else "MISSING"
    return _canonical_digest({
        "protocol_hash": protocol.protocol_hash,
        "protocol_version": protocol.protocol_version,
        "manifest": manifest.as_dict(),
        "files": files,
    })


def _persist(db, session_id: str, stage: str, content: dict, status: str,
             note: str = "") -> None:
    if db is not None and session_id:
        db.save_artifact(session_id, stage, content, status, note=note)


def invalidate(folder: Path | str, db=None, session_id: str = "",
               reason: str = "package changed; verification must run again") -> None:
    path = Path(folder) / READY_FILE
    if path.exists():
        path.unlink()
    _persist(db, session_id, "verified_ready", {"reason": reason}, "failed", reason)


def authorize(folder: Path | str, protocol: StudyProtocol, manifest: BuildManifest,
              conformance, preflight_report, db=None, session_id: str = "") -> dict:
    """Persist execution permission only when both independent gates passed."""
    if not protocol.frozen or not manifest.matches(protocol):
        raise ControlBoundaryBlocked("Design Freeze",
                                     "protocol/manifest identity is not frozen and matched")
    if conformance is None or not conformance.passed:
        raise ControlBoundaryBlocked("Scientific Conformance",
                                     conformance.summary() if conformance else "not run")
    if preflight_report is None or not preflight_report.passed:
        raise ControlBoundaryBlocked("Software Preflight",
                                     preflight_report.summary() if preflight_report else "not run")
    receipt = {
        "version": READY_VERSION,
        "status": Status.VERIFIED_READY.value,
        "protocol_hash": protocol.protocol_hash,
        "protocol_version": protocol.protocol_version,
        "manifest_hash": _canonical_digest(manifest.as_dict()),
        "package_fingerprint": package_fingerprint(folder, protocol, manifest),
        "scientific_conformance": "PASS",
        "software_preflight": "PASS",
    }
    path = Path(folder) / READY_FILE
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _persist(db, session_id, "verified_ready", receipt, "passed")
    return receipt


def require_verified_ready(folder: Path | str) -> dict:
    """Revalidate persisted permission at the last boundary before execution."""
    from agents import scientific_conformance

    folder = Path(folder)
    path = folder / READY_FILE
    if not path.exists():
        raise ControlBoundaryBlocked(
            "VERIFIED_READY", "the package has no persisted execution permission")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlBoundaryBlocked("VERIFIED_READY", f"the execution receipt is unreadable: {exc}")
    protocol = StudyProtocol.read(folder)
    manifest = BuildManifest.read(folder)
    if protocol is None or manifest is None:
        raise ControlBoundaryBlocked("VERIFIED_READY", "protocol or build manifest is missing")
    expected = {
        "status": Status.VERIFIED_READY.value,
        "protocol_hash": protocol.protocol_hash,
        "protocol_version": protocol.protocol_version,
        "manifest_hash": _canonical_digest(manifest.as_dict()),
        "package_fingerprint": package_fingerprint(folder, protocol, manifest),
        "scientific_conformance": "PASS",
        "software_preflight": "PASS",
    }
    mismatched = [key for key, value in expected.items() if receipt.get(key) != value]
    if mismatched:
        raise ControlBoundaryBlocked(
            "VERIFIED_READY",
            "the verified package changed after approval (" + ", ".join(mismatched) + ")")
    conformance = scientific_conformance.verify(folder, protocol, manifest)
    if not conformance.passed:
        raise ControlBoundaryBlocked("Scientific Conformance", conformance.summary())
    return receipt


def prepare_declared_dataset(session_id: str, db, folder: Path | str, question: str,
                             hypotheses: dict, audit: dict, tests: list[dict],
                             plan_version: int, dataset_path: Path) -> ControlOutcome:
    """Take approved dataset records through the shared production gates."""
    from agents import (build_manifest as manifest_module, intent_fidelity,
                        methodology_review, preflight, scientific_conformance)
    from agents.dataset_study import DatasetProtocolIncomplete, build_protocol
    from agents.plan_assembly import assemble
    from agents.study_builder import may_freeze

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    invalidate(folder, db, session_id, "Stage 5 package is being (re)verified")
    outcome = ControlOutcome(Status.DESIGN_IN_PROGRESS)
    try:
        protocol, approved = build_protocol(
            question, hypotheses, audit, tests, plan_version, dataset_path)
    except DatasetProtocolIncomplete as exc:
        outcome.status = Status.DESIGN_NEEDS_HUMAN
        outcome.notes.append(str(exc))
        _persist(db, session_id, "study_protocol", {"error": str(exc)}, "needs_human")
        return outcome

    protocol = intent_fidelity.propagate_identity(protocol, approved)
    outcome.protocol = protocol
    fidelity = intent_fidelity.check(protocol, approved=approved)
    methodology = methodology_review.review(protocol)
    outcome.fidelity, outcome.methodology = fidelity, methodology
    _persist(db, session_id, "intent_fidelity", fidelity.as_dict(),
             "passed" if fidelity.passed else fidelity.status.lower())
    _persist(db, session_id, "methodology_review", methodology.as_dict(),
             "passed" if methodology.approved else methodology.verdict.lower())
    intent_fidelity.write_summary(protocol, fidelity, folder, methodology)
    if not may_freeze(fidelity, methodology):
        outcome.status = (Status.INTENT_FIDELITY_FAILED if fidelity.status == "FAIL"
                          else Status.DESIGN_NEEDS_HUMAN if fidelity.status == "NEEDS_HUMAN"
                          else Status.DESIGN_REJECTED)
        outcome.notes.append(fidelity.summary() if not fidelity.passed else methodology.summary())
        _persist(db, session_id, "study_protocol", protocol.as_dict(), "blocked",
                 outcome.notes[-1])
        return outcome

    protocol = protocol.approve().freeze()
    outcome.protocol = protocol
    protocol.write(folder)
    intent_fidelity.write_summary(protocol, fidelity, folder, methodology)
    _persist(db, session_id, "study_protocol", protocol.as_dict(), "passed")

    manifest = manifest_module.plan(protocol)
    assemble(session_id, audit, tests, plan_version, protocol=protocol,
             build_manifest=manifest, folder=folder)
    manifest = BuildManifest.read(folder) or manifest
    outcome.manifest = manifest
    _persist(db, session_id, "build_manifest", manifest.as_dict(), "passed")

    conformance = scientific_conformance.verify(folder, protocol, manifest)
    outcome.conformance = conformance
    _persist(db, session_id, "scientific_conformance", conformance.as_dict(),
             "passed" if conformance.passed else "blocked")
    if not conformance.passed:
        outcome.status = Status.SCIENTIFIC_VERIFICATION_FAILED
        outcome.notes.append(conformance.summary())
        return outcome

    report = preflight.check(folder, db=db, session_id=session_id,
                             stages=preflight.BEFORE_INSTALL)
    outcome.preflight = report
    _persist(db, session_id, "software_preflight", report.as_dict(),
             "passed" if report.passed else "blocked")
    if not report.passed:
        outcome.status = Status.SOFTWARE_VERIFICATION_FAILED
        outcome.notes.append(report.summary())
        return outcome

    outcome.receipt = authorize(folder, protocol, manifest, conformance, report, db, session_id)
    outcome.status = Status.VERIFIED_READY
    return outcome


def authorize_built_study(folder: Path | str, protocol: StudyProtocol,
                          manifest: BuildManifest, db=None, session_id: str = "",
                          preflight_stages=None) -> dict:
    """Authorize a package produced by an existing family-specific builder."""
    from agents import preflight, scientific_conformance

    stages = preflight_stages or preflight.BEFORE_INSTALL
    conformance = scientific_conformance.verify(folder, protocol, manifest)
    _persist(db, session_id, "scientific_conformance", conformance.as_dict(),
             "passed" if conformance.passed else "blocked")
    if not conformance.passed:
        raise ControlBoundaryBlocked("Scientific Conformance", conformance.summary())
    report = preflight.check(Path(folder), db=db, session_id=session_id, stages=stages)
    _persist(db, session_id, "software_preflight", report.as_dict(),
             "passed" if report.passed else "blocked")
    return authorize(folder, protocol, manifest, conformance, report, db, session_id)
