"""
The scientific contract for a study, and the only thing allowed to define it.

This is the evolved form of what was `ExperimentSpec`; that name still works
and refers to this class, because two sources of scientific truth would be
worse than none.

The failure it exists for: an approved study about adversarial curation of a
choice set became a MiniGrid reinforcement-learning experiment, because nothing
between the question and the code generator ever stated what the study *was*.
Scientific decisions were re-made, implicitly, inside code generation -- and a
program that runs is not evidence that the intended experiment was implemented.

So a protocol has a lifecycle, and generation may only begin at the end of it:

    DRAFT -> METHODOLOGY_REVIEW -> APPROVED -> FROZEN

Freezing stamps a version and a hash of the scientific content. After that the
protocol is read-only to everything downstream: generated artifacts, repairs
and reruns may not change it, and a scientific change is a new version with a
new hash rather than an edit. `protocol_hash` covers the science only -- not
the prose of the question, not implementation choices -- so that rewording a
title does not invalidate results, and changing an outcome measure does.

Which fields a study must fill in depends on the family: a controlled decision
study has to say how the target is assigned and counterbalanced, and a training
study does not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path

PROTOCOL_FILE = "study_protocol.json"
# Older experiments carry the previous file name; both are read.
LEGACY_FILE = "experiment_spec.json"


class Status(str, Enum):
    DRAFT = "draft"
    METHODOLOGY_REVIEW = "methodology_review"
    APPROVED = "approved"
    FROZEN = "frozen"


class StudyType(str, Enum):
    """What kind of thing the study is, in scientific terms."""
    CONTROLLED_LLM = "controlled_llm"          # conditions applied to model decisions
    NLP_TRAINING = "nlp_training"
    CV_TRAINING = "cv_training"
    RL_TRAINING = "rl_training"
    RETRIEVAL = "retrieval"
    DOMAIN_ADAPTATION = "domain_adaptation"
    DATASET_ANALYSIS = "dataset_analysis"      # approved plan over a declared dataset


class DatasetPolicy(str, Enum):
    REQUIRED = "required"       # the study is about data it must be given
    OPTIONAL = "optional"
    NONE = "none"               # a dataset would not mean anything here


class ProtocolInvalid(ValueError):
    """The study as described cannot be run as an experiment."""


# Kept for callers that still import the old name.
SpecInvalid = ProtocolInvalid


@dataclass(frozen=True)
class OutputContract:
    path: str
    format: str = "json"
    required_keys: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"path": self.path, "format": self.format,
                "required_keys": list(self.required_keys)}


# The scientific content: everything the hash covers. Anything outside this
# list may be edited without invalidating a result.
_SCIENTIFIC_FIELDS = (
    "study_type", "causal_claim", "unit_of_analysis", "unit_of_randomization",
    "independent_variables", "dependent_variables", "conditions", "held_constant",
    "ground_truth", "sampling", "trial_structure", "randomization", "counterbalancing",
    "primary_metric", "secondary_metrics", "primary_estimand", "support_if", "reject_if",
    "known_confounds", "required_controls", "required_raw_fields", "measurement",
    "required_outputs",
    "allowed_agent_actions", "forbidden_agent_actions", "requires_training",
    "dataset_policy",
    # The identity of what is varied and measured is part of the science. Two
    # protocols with the same words and different concept ids are not the same
    # study, and the hash has to be able to say so.
    "concepts",
    # Dataset-analysis studies bind the audited source and the approved test
    # blocks directly.  These cannot be reconstructed from a single metric or
    # condition name without silently inventing science.
    "dataset_identity", "analysis_plan",
)

# What a family has to have said before its protocol may be frozen.
REQUIRED_BY_FAMILY: dict[StudyType, tuple[str, ...]] = {
    StudyType.CONTROLLED_LLM: (
        "research_question", "hypothesis", "causal_claim", "unit_of_analysis",
        "unit_of_randomization", "independent_variables", "dependent_variables",
        "conditions", "held_constant", "ground_truth", "trial_structure",
        "randomization", "counterbalancing", "primary_metric", "primary_estimand",
        "support_if", "reject_if", "required_raw_fields", "measurement", "required_outputs",
        "allowed_agent_actions", "forbidden_agent_actions",
    ),
    StudyType.DATASET_ANALYSIS: (
        "research_question", "hypothesis", "unit_of_analysis",
        "independent_variables", "dependent_variables", "primary_metric",
        "primary_estimand", "support_if", "reject_if", "required_outputs",
        "dataset_identity", "analysis_plan",
    ),
}
_DEFAULT_REQUIRED = ("research_question", "independent_variables", "dependent_variables",
                     "conditions", "primary_metric", "required_outputs")


@dataclass(frozen=True)
class StudyProtocol:
    # -- what is being asked --------------------------------------------------
    study_type: StudyType
    requires_training: bool
    dataset_policy: DatasetPolicy
    independent_variables: tuple[str, ...]
    dependent_variables: tuple[str, ...]
    held_constant: tuple[str, ...]
    conditions: tuple[str, ...]
    primary_metric: str
    secondary_metrics: tuple[str, ...]
    required_outputs: tuple[OutputContract, ...]
    scaffold_id: str
    research_question: str = ""

    # -- the rest of the science ----------------------------------------------
    hypothesis: str = ""
    causal_claim: str = ""
    unit_of_analysis: str = ""
    unit_of_randomization: str = ""
    ground_truth: str = ""
    sampling: str = ""
    trial_structure: str = ""
    randomization: str = ""
    counterbalancing: str = ""
    primary_estimand: str = ""
    support_if: str = ""
    reject_if: str = ""
    known_confounds: tuple[str, ...] = ()
    required_controls: tuple[str, ...] = ()
    required_raw_fields: tuple[str, ...] = ()
    # How each dependent variable is computed from the recorded fields. A
    # measure that is not recorded directly has to say what it is derived
    # from, or "is it operationalised?" cannot be answered: target selection
    # is not a field, it is selected_option == target_id.
    measurement: dict = field(default_factory=dict)
    allowed_agent_actions: tuple[str, ...] = ()
    forbidden_agent_actions: tuple[str, ...] = ()
    resource_constraints: dict = field(default_factory=dict)

    # -- declared-dataset authority -------------------------------------------
    # Both mappings are copied from already approved/audited artifacts. They
    # are not filled by a model at construction time.
    dataset_identity: dict = field(default_factory=dict)
    analysis_plan: dict = field(default_factory=dict)

    # -- scientific identity --------------------------------------------------
    # What each display name in this protocol *is*, as a concept id from
    # `agents/scientific_concepts.py`: {"target_selection_rate": "target_selection"}.
    # Wording is for people and changes freely; the id is the science and does
    # not. A component that renames a field and carries the entry across has
    # renamed nothing scientifically; one that renames without carrying it has
    # dropped the identity, and the gate then has to reconstruct it from the
    # words and says so. `concept_provenance` records, per display name,
    # whether the id came from the approved intent or was reconstructed.
    #
    # This is not a second source of truth. The approved intent supplies the
    # identities; after the freeze this protocol remains the scientific
    # contract, and these ids are part of what is frozen.
    concepts: dict = field(default_factory=dict)
    concept_provenance: dict = field(default_factory=dict)

    # -- lifecycle ------------------------------------------------------------
    status: Status = Status.DRAFT
    protocol_version: int = 0
    frozen_at: str = ""

    # ------------------------------------------------------------------
    @property
    def protocol_hash(self) -> str:
        """A hash of the science, and only the science."""
        payload = {name: _canonical(getattr(self, name)) for name in _SCIENTIFIC_FIELDS}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    @property
    def frozen(self) -> bool:
        return self.status is Status.FROZEN

    def required_fields(self) -> tuple[str, ...]:
        return REQUIRED_BY_FAMILY.get(self.study_type, _DEFAULT_REQUIRED)

    # -- checking ------------------------------------------------------------
    def problems(self) -> list[str]:
        """Everything wrong with this as a description of an experiment."""
        found: list[str] = []
        if self.study_type is StudyType.CONTROLLED_LLM and len(self.conditions) < 2:
            found.append("an experiment compares at least two conditions; "
                         f"this one names {len(self.conditions)}")
        if len(set(self.conditions)) != len(self.conditions):
            found.append("the same condition is named twice")
        if not self.independent_variables:
            found.append("nothing is said to vary")
        if not self.dependent_variables:
            found.append("nothing is said to be measured")
        if not self.primary_metric:
            found.append("there is no primary outcome")
        if self.primary_metric in self.secondary_metrics:
            found.append("the primary outcome is also listed as secondary")
        if not self.required_outputs:
            found.append("the experiment does not say what it must write")
        if self.requires_training and self.dataset_policy is DatasetPolicy.NONE:
            found.append("a study that trains something needs data to train on")
        if not self.scaffold_id:
            found.append("no scaffold can implement this")
        overlap = set(self.independent_variables) & set(self.held_constant)
        if overlap:
            found.append(f"{', '.join(sorted(overlap))} is both varied and held constant")

        for name in self.required_fields():
            value = getattr(self, name, None)
            if not value:
                found.append(f"{name.replace('_', ' ')} is not stated, and this family "
                             "of study cannot be run without it")
        return found

    def validate(self) -> "StudyProtocol":
        problems = self.problems()
        if problems:
            raise ProtocolInvalid("; ".join(problems))
        return self

    # -- lifecycle steps -----------------------------------------------------
    def submit_for_review(self) -> "StudyProtocol":
        return replace(self, status=Status.METHODOLOGY_REVIEW)

    def approve(self) -> "StudyProtocol":
        """Only a methodology review may call this (see agents/methodology_review.py)."""
        return replace(self.validate(), status=Status.APPROVED)

    def freeze(self, version: int | None = None) -> "StudyProtocol":
        """
        Fix the science. Everything downstream reads it and nothing writes it.

        Freezing an unapproved protocol is refused: approval is the step where
        the design is judged, and skipping it would make the gate decorative.
        """
        if self.status not in (Status.APPROVED, Status.FROZEN):
            raise ProtocolInvalid(
                f"a protocol is frozen after it is approved, not while it is {self.status.value}")
        from datetime import datetime, timezone

        return replace(self.validate(), status=Status.FROZEN,
                       protocol_version=version or max(self.protocol_version, 1),
                       frozen_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def revise(self, **changes) -> "StudyProtocol":
        """
        A scientific change is a new version, never an edit of a frozen one.

        The new protocol starts at DRAFT: a change to the science has to go
        back through review, which is the whole point of freezing.
        """
        return replace(self, status=Status.DRAFT,
                       protocol_version=self.protocol_version + 1,
                       frozen_at="", **changes)

    # -- reading and writing -------------------------------------------------
    def as_dict(self) -> dict:
        data = asdict(self)
        data["study_type"] = self.study_type.value
        data["dataset_policy"] = self.dataset_policy.value
        data["status"] = self.status.value
        data["required_outputs"] = [o.as_dict() for o in self.required_outputs]
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        data["protocol_hash"] = self.protocol_hash
        return data

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)

    def write(self, folder: Path | str) -> Path:
        path = Path(folder) / PROTOCOL_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json() + "\n", encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "StudyProtocol":
        known = {f for f in cls.__dataclass_fields__}
        values: dict = {}
        for key, value in data.items():
            if key not in known:
                continue
            values[key] = value
        values["study_type"] = StudyType(data["study_type"])
        values["dataset_policy"] = DatasetPolicy(data["dataset_policy"])
        values["status"] = Status(data.get("status", Status.DRAFT.value))
        values["required_outputs"] = tuple(
            OutputContract(path=o["path"], format=o.get("format", "json"),
                           required_keys=tuple(o.get("required_keys", ())))
            for o in data.get("required_outputs", ()))
        for key in ("independent_variables", "dependent_variables", "held_constant",
                    "conditions", "secondary_metrics", "known_confounds",
                    "required_controls", "required_raw_fields", "allowed_agent_actions",
                    "forbidden_agent_actions"):
            if key in values:
                values[key] = tuple(values[key] or ())
        protocol = cls(**values)
        stated = data.get("protocol_hash")
        if stated and stated != protocol.protocol_hash:
            raise ProtocolInvalid(
                f"the protocol file's science does not match its hash (stated {stated}, "
                f"computed {protocol.protocol_hash}): it has been edited since it was frozen")
        return protocol

    @classmethod
    def read(cls, folder: Path | str) -> "StudyProtocol | None":
        folder = Path(folder)
        for name in (PROTOCOL_FILE, LEGACY_FILE):
            path = folder / name
            if path.exists():
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return None


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    if isinstance(value, OutputContract):
        return value.as_dict()
    return value


# The previous name for this class. One definition, two names, so nothing that
# already imports ExperimentSpec has to change to keep working.
ExperimentSpec = StudyProtocol
