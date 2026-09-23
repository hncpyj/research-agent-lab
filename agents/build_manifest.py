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

import json
from dataclasses import asdict, dataclass, field
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

    def as_dict(self) -> dict:
        data = asdict(self)
        data["execution_tier"] = self.execution_tier.value
        data["trusted_modules"] = [list(pair) for pair in self.trusted_modules]
        data["generated_artifacts"] = [a.as_dict() for a in self.generated_artifacts]
        for key in ("deterministic_artifacts", "contract_tests",
                    "scientific_conformance_rules", "smoke_command"):
            data[key] = list(getattr(self, key))
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
