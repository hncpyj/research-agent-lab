"""
How a frozen protocol gets built, written down separately from what it is.

Two different kinds of truth were living in one place. What a study
establishes is scientific; which files implement it, which of them a model is
allowed to write, and what command rehearses them are engineering. Keeping
them in one object is how implementation convenience ends up editing the
science -- a template that needs a dataset acquires one, a generator that finds
a loop hard writes a different loop.

    StudyProtocol   what must be established        (frozen, hashed)
    BuildManifest   how it is implemented           (derived from the hash)

The manifest carries the protocol's hash, so an implementation can always be
checked against the science it was planned for; if the science changes, the
hash changes and the old manifest no longer matches.

`execution_tier` is the important field. It says how much the model is trusted
to write:

    DECLARATIVE   trusted code runs the study; the model writes content only
    PLUGIN        the model writes one component against a fixed interface
    OPEN_ENDED    the model writes the program (where nothing else can work)

A controlled decision study is DECLARATIVE. It was not, and that is exactly
where it went wrong: asked for the driver, an 8B model produced a loop that
discarded its own curation and a config naming conditions the design never had.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path

MANIFEST_FILE = "build_manifest.json"


class Tier(str, Enum):
    DECLARATIVE = "declarative"
    PLUGIN = "plugin"
    OPEN_ENDED = "open_ended"


class Status(str, Enum):
    """
    Where a study is, including the ways it can stop that are nobody's mistake.

    "No code was generated" used to cover a credit-exhausted provider, an
    unreachable local model and a design that was refused, which are three
    different situations with three different answers.
    """
    NOT_STARTED = "not_started"
    DESIGN_IN_PROGRESS = "design_in_progress"
    DESIGN_REJECTED = "design_rejected"
    # Kept apart from DESIGN_REJECTED: the design may be perfectly sound and
    # still not be the study that was approved.
    INTENT_FIDELITY_FAILED = "intent_fidelity_failed"
    DESIGN_NEEDS_HUMAN = "design_needs_human"
    GENERATION_IN_PROGRESS = "generation_in_progress"
    GENERATION_BLOCKED_RESOURCE = "generation_blocked_resource"
    GENERATION_FAILED_MODEL_OUTPUT = "generation_failed_model_output"
    GENERATED_UNVERIFIED = "generated_unverified"
    SCIENTIFIC_VERIFICATION_FAILED = "scientific_verification_failed"
    SOFTWARE_VERIFICATION_FAILED = "software_verification_failed"
    VERIFIED_READY = "verified_ready"
    EXECUTION_IN_PROGRESS = "execution_in_progress"
    EXECUTION_FAILED = "execution_failed"
    COMPLETED = "completed"


# The manifest's own schema version. It is recorded in every manifest, so a
# manifest written before trusted-artifact integrity existed is recognisable as
# one that cannot be checked for it, rather than one that passed the check.
MANIFEST_VERSION = 2


@dataclass(frozen=True)
class TrustedArtifact:
    """
    One apparatus file, bound to the plan by its content rather than its name.

    Naming a module in the manifest said which file was supposed to be there.
    It did not say what was supposed to be in it, and an injected fault that
    kept every symbol the conformance rule looked for while discarding the
    randomisation the protocol required passed every layer and produced an
    accepted result (F-C5, 20260922). A hash is what closes that: the file
    either is the trusted file or it is not.
    """
    path: str
    sha256: str
    role: str

    def as_dict(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "role": self.role}


def file_hash(path: Path) -> str:
    """
    The hash a trusted artifact is bound by.

    Line endings are normalised first, so that the same file checked out on
    another platform is the same artifact and not an integrity failure.
    """
    body = path.read_bytes().replace(bytes([13, 10]), bytes([10]))
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class ArtifactSchema:
    """What a generated artifact has to look like to be accepted."""
    path: str
    format: str                       # json | jsonl | python | text
    required_keys: tuple[str, ...] = ()
    description: str = ""

    def as_dict(self) -> dict:
        return {"path": self.path, "format": self.format,
                "required_keys": list(self.required_keys), "description": self.description}


@dataclass(frozen=True)
class BuildManifest:
    protocol_hash: str
    protocol_version: int
    execution_tier: Tier
    scaffold_id: str
    selection_reason: str
    trusted_modules: tuple[tuple[str, str], ...]      # (source in tools/, name in folder)
    generated_artifacts: tuple[ArtifactSchema, ...]
    deterministic_artifacts: tuple[str, ...]          # written by trusted code, not a model
    entrypoints: dict                                  # phase -> script
    dependency_policy: str
    output_locations: dict
    contract_tests: tuple[str, ...]
    scientific_conformance_rules: tuple[str, ...]
    smoke_command: tuple[str, ...]
    # Filled in by `seal` once the apparatus has been copied into the study
    # folder: the plan binds the content of every trusted file, not its name.
    trusted_artifacts: tuple[TrustedArtifact, ...] = ()
    # The scientific identities the approved intent assigned, carried forward so
    # that a later layer compares identity rather than wording.
    concepts: dict = field(default_factory=dict)
    manifest_version: int = MANIFEST_VERSION
    # Explicit execution contract fields used by deterministic analysis
    # packages as well as open-ended generators.
    required_result_fields: tuple[str, ...] = ()
    execution_command: tuple[str, ...] = ()
    repair_policy: str = "mechanical_only_then_revalidate"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["execution_tier"] = self.execution_tier.value
        data["trusted_modules"] = [list(pair) for pair in self.trusted_modules]
        data["generated_artifacts"] = [a.as_dict() for a in self.generated_artifacts]
        for key in ("deterministic_artifacts", "contract_tests",
                    "scientific_conformance_rules", "smoke_command",
                    "required_result_fields", "execution_command"):
            data[key] = list(getattr(self, key))
        data["trusted_artifacts"] = [a.as_dict() for a in self.trusted_artifacts]
        data["concepts"] = dict(self.concepts)
        data["manifest_version"] = self.manifest_version
        return data

    def write(self, folder: Path | str) -> Path:
        path = Path(folder) / MANIFEST_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "BuildManifest":
        return cls(
            protocol_hash=data["protocol_hash"],
            protocol_version=int(data.get("protocol_version", 0)),
            execution_tier=Tier(data["execution_tier"]),
            scaffold_id=data["scaffold_id"],
            selection_reason=data.get("selection_reason", ""),
            trusted_modules=tuple(tuple(pair) for pair in data.get("trusted_modules", ())),
            generated_artifacts=tuple(
                ArtifactSchema(path=a["path"], format=a["format"],
                               required_keys=tuple(a.get("required_keys", ())),
                               description=a.get("description", ""))
                for a in data.get("generated_artifacts", ())),
            deterministic_artifacts=tuple(data.get("deterministic_artifacts", ())),
            entrypoints=data.get("entrypoints", {}),
            dependency_policy=data.get("dependency_policy", ""),
            output_locations=data.get("output_locations", {}),
            contract_tests=tuple(data.get("contract_tests", ())),
            scientific_conformance_rules=tuple(data.get("scientific_conformance_rules", ())),
            smoke_command=tuple(data.get("smoke_command", ())),
            trusted_artifacts=tuple(
                TrustedArtifact(path=a["path"], sha256=a["sha256"], role=a.get("role", ""))
                for a in data.get("trusted_artifacts", ())),
            concepts=dict(data.get("concepts", {}) or {}),
            manifest_version=int(data.get("manifest_version", 1)),
            required_result_fields=tuple(data.get("required_result_fields", ())),
            execution_command=tuple(data.get("execution_command", ())),
            repair_policy=data.get("repair_policy", "mechanical_only_then_revalidate"),
        )

    @classmethod
    def read(cls, folder: Path | str) -> "BuildManifest | None":
        path = Path(folder) / MANIFEST_FILE
        if not path.exists():
            return None
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def matches(self, protocol) -> bool:
        """Whether this plan was made for this exact science."""
        return self.protocol_hash == protocol.protocol_hash


class NoPlanPossible(RuntimeError):
    """Nothing in this system can implement that protocol."""


def plan(protocol) -> BuildManifest:
    """
    The implementation plan for a frozen protocol.

    Refuses an unfrozen one: planning from a design that can still change is
    how an implementation ends up built for a study nobody approved.
    """
    from agents.study_protocol import Status as ProtocolStatus

    if protocol.status is not ProtocolStatus.FROZEN:
        raise NoPlanPossible(
            f"the protocol is {protocol.status.value}; nothing may be built from it "
            "until it is reviewed, approved and frozen")

    if protocol.scaffold_id == "controlled_llm":
        from agents import controlled_llm_scaffold as scaffold
        return scaffold.build_manifest(protocol)

    if protocol.scaffold_id == "analysis_plan":
        from agents.plan_assembly import COPIED

        return BuildManifest(
            protocol_hash=protocol.protocol_hash,
            protocol_version=protocol.protocol_version,
            execution_tier=Tier.DECLARATIVE,
            scaffold_id="analysis_plan",
            selection_reason=("trusted deterministic analysis blocks assemble the exact "
                              "human-approved TEST plan"),
            trusted_modules=tuple((name, name) for name in COPIED),
            generated_artifacts=(),
            deterministic_artifacts=("config.json", "requirements.txt", "manifest.json"),
            entrypoints={"analysis": "run_analysis.py"},
            dependency_policy="fixed numpy/pandas/scipy requirements",
            output_locations={"results": "results/"},
            contract_tests=("legacy assembly hashes", "approved test contract"),
            scientific_conformance_rules=(
                "protocol identity", "dataset identity", "variables and columns",
                "approved analysis blocks", "estimands and decision rules",
                "required result fields", "trusted apparatus integrity"),
            smoke_command=(),
            concepts=dict(protocol.concepts),
            required_result_fields=tuple(protocol.required_raw_fields),
            execution_command=("python", "run_analysis.py"),
            repair_policy="no generated code; rebuild deterministically from frozen protocol",
        )

    # The training families keep the implementation path they already had. They
    # are planned as OPEN_ENDED, which is what they have always been -- stated
    # here rather than assumed.
    from agents.experiment_agent import scaffold_by_id

    domain = scaffold_by_id(protocol.scaffold_id)
    return BuildManifest(
        protocol_hash=protocol.protocol_hash,
        protocol_version=protocol.protocol_version,
        execution_tier=Tier.OPEN_ENDED,
        scaffold_id=protocol.scaffold_id,
        selection_reason=("a training study: the model writes the program, as it has "
                          "always done for this family"),
        trusted_modules=tuple(domain.copied_files),
        generated_artifacts=tuple(
            ArtifactSchema(path=path, format=language) for path, _, language in domain.file_specs),
        deterministic_artifacts=(),
        entrypoints={"train": "train.py", "evaluate": "evaluate.py"},
        dependency_policy="generated requirements, relaxed to install, versions recorded",
        output_locations={"results": "results/"},
        contract_tests=(),
        scientific_conformance_rules=(),
        smoke_command=(),
    )


# --- binding the plan to the apparatus it planned -------------------------------------

def seal(manifest: BuildManifest, folder: Path | str,
         roles: dict | None = None, concepts: dict | None = None) -> BuildManifest:
    """
    Record the content of every trusted artifact that is now on disk.

    Called once, after trusted code has copied the apparatus into the study
    folder and before anything is generated or verified. The manifest then
    carries a hash of each file rather than only its name, which is the
    difference between a plan that says what should be there and a plan that
    says what it is.

    Only files trusted code wrote are sealed. A generated artifact is checked
    against its schema and its science, not against a hash, because the whole
    point of it is that a model wrote it.
    """
    folder = Path(folder)
    roles = roles or {}
    sealed: list[TrustedArtifact] = []
    bound = [name for _, name in manifest.trusted_modules]
    if manifest.scaffold_id == "analysis_plan":
        # In this family the config and legacy execution manifest are produced
        # by trusted deterministic assembly, so their exact bytes are part of
        # the implementation identity too.
        bound.extend(manifest.deterministic_artifacts)
    for name in dict.fromkeys(bound):
        path = folder / name
        if path.exists():
            sealed.append(TrustedArtifact(
                path=name, sha256=file_hash(path),
                role=roles.get(name, "trusted apparatus copied from tools/")))
    # In model-authored families deterministic config is compared with the
    # protocol clause by clause rather than sealed by bytes: a harmless
    # reserialisation is not a scientific mutation.  The analysis-plan family
    # is different: trusted assembly writes its config and legacy manifest, so
    # the branch above seals those exact artifacts along with its apparatus.
    return replace(manifest, trusted_artifacts=tuple(sealed),
                   concepts=dict(concepts or manifest.concepts))


@dataclass
class IntegrityFinding:
    path: str
    role: str
    expected: str
    found: str
    problem: str          # missing | modified


def verify_trusted_artifacts(manifest: BuildManifest,
                             folder: Path | str) -> list[IntegrityFinding]:
    """
    Whether every trusted artifact is still the one the plan was sealed around.

    Returns what is wrong, and an empty list when nothing is. It does not look
    at what a file contains or which identifiers appear in it: a file whose
    hash matches is the trusted file, and a file whose hash does not is not,
    whatever it has been made to look like.
    """
    folder = Path(folder)
    findings: list[IntegrityFinding] = []
    for artifact in manifest.trusted_artifacts:
        path = folder / artifact.path
        if not path.exists():
            findings.append(IntegrityFinding(artifact.path, artifact.role,
                                             artifact.sha256, "", "missing"))
            continue
        found = file_hash(path)
        if found != artifact.sha256:
            findings.append(IntegrityFinding(artifact.path, artifact.role,
                                             artifact.sha256, found, "modified"))
    return findings
