"""
The path from a question to a study that can be run, in order, with gates.

Each step used to be able to redecide the previous one. The order here is the
point:

    protocol      what the study is                  (built from the hypothesis)
    review        whether the design can carry it    (a gate, not advice)
    freeze        the science, versioned and hashed
    manifest      how it will be implemented
    deterministic the apparatus, config, requirements  (trusted code writes these)
    generate      the study-specific content          (a model writes only this)
    conformance   is this the study that was approved (a gate)
    preflight     does the software work              (a separate gate)

Nothing skips forward. A design that fails review is not generated. A
generation that fails conformance is regenerated from the protocol -- not
repaired, because repair makes code run and running was never the problem. If
conformance cannot be satisfied without changing the protocol, this stops and
says so: at that point the disagreement is scientific and a new protocol
version is the only honest answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from agents.build_manifest import Status

logger = logging.getLogger(__name__)


@dataclass
class BuildOutcome:
    status: Status
    folder: Path | None = None
    protocol = None
    manifest = None
    fidelity = None
    review = None
    conformance = None
    preflight = None
    generation = None
    summary_path = None
    notes: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status is Status.VERIFIED_READY

    def summary(self) -> str:
        return f"{self.status.value}" + (f": {self.notes[0]}" if self.notes else "")


def may_freeze(fidelity, review) -> bool:
    """
    The one place the two verdicts meet, and the only way they may combine.

    Both must pass. A methodology PASS never clears a fidelity FAIL, and a
    fidelity PASS never clears a methodology FAIL; NEEDS_HUMAN from either one
    blocks, because "someone should look at this" is not permission.
    """
    from agents import intent_fidelity, methodology_review

    return (fidelity is not None and review is not None
            and fidelity.status == intent_fidelity.PASS
            and review.verdict == methodology_review.PASS)


def build(hypothesis: str, api_model, folder: Path | str, *,
          approved=None, protocol=None,
          design: dict | None = None, reviewer=None, num_trials: int = 20,
          curator: str = "", overseer: str = "", backend: str = "ollama",
          run_preflight: bool = True) -> BuildOutcome:
    """
    Take one hypothesis all the way to a verified, runnable study.

    `api_model` writes the content. `reviewer`, if given, is asked for doubts
    about the design; it can send a passing design to NEEDS_HUMAN and can never
    approve one that failed a mechanical check.

    `protocol` is a already-drafted StudyProtocol to take through the gates
    instead of deriving one from `hypothesis`. It changes nothing about how it
    is checked.

    `approved` is the ranked record of what a person signed off -- an
    `intent_fidelity.ApprovedIntent`. Without one, the protocol's own question
    and hypothesis stand in for it, which is weaker: a commitment that lives
    only in a structured approval cannot then be enforced, and a choice nobody
    approved is harder to tell from one somebody did.
    """
    from agents import build_manifest as manifest_module
    from agents import intent_fidelity, methodology_review, scientific_conformance
    from agents.experiment_agent import build_spec

    folder = Path(folder)
    outcome = BuildOutcome(status=Status.DESIGN_IN_PROGRESS, folder=folder)

    # -- 1. what the study is -------------------------------------------------
    # A protocol drafted upstream may be handed in; otherwise it is derived
    # from the hypothesis here. Either way it is an input to the gates below
    # and is never trusted because of where it came from.
    protocol = protocol if protocol is not None else build_spec(hypothesis, design or {})
    # Attach the scientific identity of each name before anything compares
    # them, and before the freeze, so the ids are part of what is frozen. A
    # rename that carries its id across is then free; one that drops it is
    # visible as a reconstructed identity rather than passing unnoticed.
    protocol = intent_fidelity.propagate_identity(protocol, approved)
    outcome.protocol = protocol

    # -- 2. is it still the study that was asked for? -------------------------
    # Before the methodology review, and never merged with it: a sound design
    # for a different question is the failure this system exists to prevent,
    # and it would pass a review that only asks whether the design is sound.
    fidelity = intent_fidelity.check(protocol, reviewer=reviewer, approved=approved)
    outcome.fidelity = fidelity

    # -- 3. is the design sound? ----------------------------------------------
    review = methodology_review.review(protocol, reviewer=reviewer)
    outcome.review = review

    # -- 4. the human-visible boundary ----------------------------------------
    # Written whatever the verdicts are: a refusal is exactly when someone
    # needs to be able to read what was proposed.
    folder.mkdir(parents=True, exist_ok=True)
    outcome.summary_path = intent_fidelity.write_summary(protocol, fidelity, folder, review)

    if not may_freeze(fidelity, review):
        outcome.status = (Status.INTENT_FIDELITY_FAILED if fidelity.status == "FAIL"
                          else Status.DESIGN_NEEDS_HUMAN if fidelity.status == "NEEDS_HUMAN"
                          else Status.DESIGN_REJECTED)
        outcome.notes.append(fidelity.summary() if not fidelity.passed else review.summary())
        return outcome

    # -- 5. freeze it ---------------------------------------------------------
    protocol = protocol.approve().freeze()
    outcome.protocol = protocol
    outcome.notes.append(f"protocol v{protocol.protocol_version} "
                         f"({protocol.protocol_hash}) frozen")
    # Rewrite the summary against the frozen protocol, so the persisted
    # boundary carries the hash the study was actually built from.
    outcome.summary_path = intent_fidelity.write_summary(protocol, fidelity, folder, review)

    # -- 6. how it will be built ----------------------------------------------
    manifest = manifest_module.plan(protocol)
    outcome.manifest = manifest

    if manifest.execution_tier is not manifest_module.Tier.DECLARATIVE:
        # The training families keep their existing path; this controller is
        # only the route for families whose apparatus is trusted code.
        outcome.status = Status.DESIGN_IN_PROGRESS
        outcome.notes.append(f"{manifest.scaffold_id} is built by the existing "
                             "generation path, not by this controller")
        return outcome

    from agents import controlled_llm_scaffold as scaffold

    # -- 7. everything a model has no business deciding -----------------------
    scaffold.write_deterministic(protocol, manifest, folder, num_trials=num_trials,
                                 curator=curator, overseer=overseer, backend=backend)
    # Writing the apparatus is what lets the plan be sealed around it, so the
    # manifest on disk is the one that carries the artifact hashes and the one
    # every later layer is checked against.
    manifest = manifest_module.BuildManifest.read(folder) or manifest
    outcome.manifest = manifest

    # -- 8. the study-specific content ----------------------------------------
    outcome.status = Status.GENERATION_IN_PROGRESS
    generation = scaffold.generate(protocol, api_model, folder)
    outcome.generation = generation
    if not generation.ok:
        outcome.status = generation.status
        outcome.notes.append(generation.reason or "generation did not produce artifacts")
        return outcome
    outcome.status = Status.GENERATED_UNVERIFIED

    # -- 9. do the artifacts match the frozen protocol? ------------------------------
    conformance = scientific_conformance.verify(folder, protocol, manifest)
    if not conformance.passed and conformance.artifacts_to_regenerate and \
            not conformance.needs_new_protocol:
        outcome.notes.append("regenerating " +
                             ", ".join(conformance.artifacts_to_regenerate) +
                             " from the frozen protocol")
        generation = scaffold.generate(protocol, api_model, folder)
        outcome.generation = generation
        if not generation.ok:
            outcome.status = generation.status
            outcome.notes.append(generation.reason or "regeneration failed")
            return outcome
        conformance = scientific_conformance.verify(folder, protocol, manifest)
    outcome.conformance = conformance
    if not conformance.passed:
        outcome.status = Status.SCIENTIFIC_VERIFICATION_FAILED
        outcome.notes.append(conformance.summary())
        if conformance.needs_new_protocol:
            outcome.notes.append("this cannot be fixed by regenerating: it needs a new "
                                 "protocol version, reviewed and frozen again")
        return outcome

    # -- 10. does the software work? -------------------------------------------
    if run_preflight:
        from agents import preflight as preflight_module

        report = preflight_module.check(folder, stages=(preflight_module.COMPILE,
                                                        preflight_module.CONTRACT,
                                                        preflight_module.IMPORTS,
                                                        preflight_module.SMOKE))
        outcome.preflight = report
        if not report.passed:
            outcome.status = Status.SOFTWARE_VERIFICATION_FAILED
            outcome.notes.append(report.summary())
            return outcome

    outcome.status = Status.VERIFIED_READY
    return outcome
