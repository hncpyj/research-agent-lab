"""
Judging the design before anything is built from it.

The step that designs an experiment must not also be the step that approves it.
When they are the same step, "is this the right experiment?" is answered by
whoever just decided it was -- which is how a study of adversarial curation
passed straight into a reinforcement-learning template with a critical note
recorded beside it and nothing stopping it.

So review is separate, and it answers one of three things:

    PASS         the design can carry the claim it makes
    FAIL         it cannot, and no amount of good code will fix that
    NEEDS_HUMAN  it might, but the judgement is not mechanical

Everything here is mechanical: it reads the protocol and checks that the
pieces a claim needs are present and consistent. A model may add an opinion on
top (`review(..., reviewer=api_model)`), and its opinion can move PASS to
NEEDS_HUMAN -- it can never move FAIL to PASS. A language model's approval is
not evidence, and a mechanically detected hole does not close because something
fluent says it is fine.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from agents.study_protocol import DatasetPolicy, StudyProtocol, StudyType

logger = logging.getLogger(__name__)

PASS, FAIL, NEEDS_HUMAN = "PASS", "FAIL", "NEEDS_HUMAN"


@dataclass
class Finding:
    severity: str          # "blocking" | "question"
    check: str
    message: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "check": self.check, "message": self.message}


@dataclass
class Review:
    verdict: str
    findings: list[Finding] = field(default_factory=list)
    reviewer_notes: str = ""

    @property
    def intent_fidelity(self) -> str:
        """
        Recorded separately from the verdict, because it answers a different
        question: not "is this a sound design" but "is this the design that was
        asked for". A study can be impeccable and about something else.
        """
        relevant = [f for f in self.findings if f.check == "intent_fidelity"]
        if any(f.severity == "blocking" for f in relevant):
            return FAIL
        return NEEDS_HUMAN if relevant else PASS

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def approved(self) -> bool:
        return self.verdict == PASS

    def summary(self) -> str:
        if self.approved:
            return "Methodology review passed."
        first = (self.blocking or self.findings)[0]
        return f"Methodology review {self.verdict.lower()}: {first.message}"

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "findings": [f.as_dict() for f in self.findings],
                "reviewer_notes": self.reviewer_notes}


# --- the mechanical checks ----------------------------------------------------------

def _isolation(protocol: StudyProtocol) -> list[Finding]:
    """Does what varies vary alone?"""
    found = []
    if not protocol.independent_variables:
        found.append(Finding("blocking", "isolation", "nothing is said to vary"))
    if len(protocol.independent_variables) > 1:
        found.append(Finding("question", "isolation",
                             f"{len(protocol.independent_variables)} things vary at once "
                             f"({', '.join(protocol.independent_variables)}); an effect "
                             "cannot be attributed to one of them"))
    if not protocol.held_constant:
        found.append(Finding("blocking", "isolation",
                             "nothing is held constant, so any difference between "
                             "conditions has more than one explanation"))
    overlap = set(protocol.independent_variables) & set(protocol.held_constant)
    if overlap:
        found.append(Finding("blocking", "isolation",
                             f"{', '.join(sorted(overlap))} is both varied and held constant"))
    return found


def _ground_truth(protocol: StudyProtocol) -> list[Finding]:
    """Is there something independent of the agents to measure against?"""
    found = []
    if protocol.study_type is StudyType.CONTROLLED_LLM and not protocol.ground_truth:
        found.append(Finding("blocking", "ground_truth",
                             "a controlled decision study needs ground truth that the "
                             "agents cannot change; none is stated"))
    if protocol.dataset_policy is DatasetPolicy.REQUIRED and not (
            protocol.ground_truth or protocol.sampling):
        found.append(Finding("question", "ground_truth",
                             "a study on data should say what the data is and how it "
                             "is sampled"))
    return found


def _operationalised(protocol: StudyProtocol) -> list[Finding]:
    """Can each variable actually be recorded?"""
    found = []
    if not protocol.dependent_variables:
        found.append(Finding("blocking", "operationalisation", "nothing is measured"))
    if not protocol.primary_metric:
        found.append(Finding("blocking", "operationalisation", "there is no primary outcome"))
    if protocol.required_raw_fields:
        recorded = set(protocol.required_raw_fields)
        for variable in protocol.dependent_variables:
            sources = protocol.measurement.get(variable)
            if sources:
                missing = [s for s in sources if s not in recorded]
                if missing:
                    found.append(Finding(
                        "blocking", "operationalisation",
                        f"{variable} is computed from {', '.join(missing)}, which "
                        "no trial records"))
                continue
            if variable not in recorded:
                found.append(Finding("blocking", "operationalisation",
                                     f"{variable} is measured but nothing says how: it is "
                                     "neither a recorded field nor derived from any"))
    return found


def _metric_matches_claim(protocol: StudyProtocol) -> list[Finding]:
    """
    Does the primary outcome measure the thing the hypothesis is about?

    Checked by the words they share, which is crude but catches the case that
    matters: an outcome about something else entirely.
    """
    found = []
    claim = f"{protocol.hypothesis} {protocol.causal_claim} {protocol.research_question}".lower()
    if not claim.strip():
        return [Finding("blocking", "claim", "no hypothesis or causal claim is stated")]
    stem = protocol.primary_metric.replace("_rate", "").replace("_", " ")
    words = [w for w in stem.split() if len(w) > 3]
    if words and not any(w in claim for w in words):
        found.append(Finding("question", "claim",
                             f"the primary outcome ({protocol.primary_metric}) does not "
                             "obviously measure what the hypothesis is about"))
    return found


def _randomisation(protocol: StudyProtocol) -> list[Finding]:
    """Where a family needs randomisation, is it defined?"""
    if protocol.study_type is not StudyType.CONTROLLED_LLM:
        return []
    found = []
    if not protocol.randomization:
        found.append(Finding("blocking", "randomisation",
                             "nothing says how the target and the presentation order are "
                             "randomised, so position or identity could explain the result"))
    if not protocol.counterbalancing:
        found.append(Finding("question", "randomisation",
                             "no counterbalancing is stated; with few trials a target "
                             "drawn at random can still be unbalanced"))
    return found


def _falsifiable(protocol: StudyProtocol) -> list[Finding]:
    """Is there an outcome that would count against the hypothesis?"""
    found = []
    if not protocol.support_if:
        found.append(Finding("blocking", "falsifiability",
                             "nothing says what result would support the hypothesis"))
    if not protocol.reject_if:
        found.append(Finding("blocking", "falsifiability",
                             "nothing says what result would count against it, so no "
                             "outcome could disconfirm anything"))
    if protocol.support_if and protocol.reject_if and \
            protocol.support_if.strip() == protocol.reject_if.strip():
        found.append(Finding("blocking", "falsifiability",
                             "the same result is said to support and to refute the claim"))
    return found


def _confounds(protocol: StudyProtocol) -> list[Finding]:
    """Are the confounds it knows about actually controlled?"""
    if protocol.study_type is not StudyType.CONTROLLED_LLM:
        return []
    if not protocol.known_confounds:
        return [Finding("question", "confounds", "no confounds are named")]
    if not protocol.required_controls:
        return [Finding("blocking", "confounds",
                        f"{len(protocol.known_confounds)} confound(s) are named and "
                        "nothing is done about any of them")]
    return []


def _units(protocol: StudyProtocol) -> list[Finding]:
    found = []
    if not protocol.unit_of_analysis:
        found.append(Finding("blocking", "units", "the unit of analysis is not stated"))
    if protocol.study_type is StudyType.CONTROLLED_LLM and not protocol.unit_of_randomization:
        found.append(Finding("blocking", "units", "the unit of randomisation is not stated"))
    return found


def _agent_actions(protocol: StudyProtocol) -> list[Finding]:
    """A controlled study has to say what the agents may and may not do."""
    if protocol.study_type is not StudyType.CONTROLLED_LLM:
        return []
    found = []
    if not protocol.allowed_agent_actions:
        found.append(Finding("blocking", "agent_actions",
                             "nothing says what the agents are allowed to do"))
    if not protocol.forbidden_agent_actions:
        found.append(Finding("blocking", "agent_actions",
                             "nothing says what they may not do, and the study rests on "
                             "the curator not being able to change the candidates"))
    return found


def _intent_fidelity(protocol) -> list[Finding]:
    """
    Whether the protocol still expresses the question it came from.

    A perfectly executed wrong protocol is still a scientific failure, and this
    is the only check positioned to catch it: everything after freezing
    compares artifacts against the protocol, so a protocol that already drifted
    would be implemented faithfully and be wrong.

    Mechanical and deliberately narrow: it compares the words of the question
    with the words of the design. It cannot tell whether a paraphrase preserved
    meaning, so a doubt here is a question for a person, not a refusal.
    """
    found = []
    question = f"{protocol.research_question} {protocol.hypothesis}".lower()
    if not question.strip():
        return [Finding("blocking", "intent_fidelity",
                        "the protocol does not record the question it came from, so "
                        "nothing can check that it still expresses it")]

    # Every condition the question names must survive into the design.
    for word in ("benign", "adversarial", "neutral", "control", "baseline"):
        if word in question and not any(word in c for c in protocol.conditions):
            found.append(Finding("question", "intent_fidelity",
                                 f"the question mentions a {word} condition and the "
                                 "design has none by that name"))

    # The outcome the question is about must be the outcome that is measured.
    if "approv" in question and not any("approval" in m for m in
                                        (protocol.primary_metric,) + tuple(protocol.secondary_metrics)):
        found.append(Finding("blocking", "intent_fidelity",
                             "the question is about approval and no outcome measures it"))
    if "select" in question and "select" not in protocol.primary_metric:
        found.append(Finding("question", "intent_fidelity",
                             "the question is about selection and the primary outcome is "
                             f"{protocol.primary_metric}"))

    # A claim the question does not make.
    if protocol.causal_claim:
        claim_words = {w for w in protocol.causal_claim.lower().split() if len(w) > 6}
        question_words = {w for w in question.split() if len(w) > 6}
        if claim_words and not (claim_words & question_words):
            found.append(Finding("question", "intent_fidelity",
                                 "the causal claim shares no substantive term with the "
                                 "question it is supposed to formalise"))
    return found


_CHECKS = (_intent_fidelity, _isolation, _ground_truth, _operationalised,
           _metric_matches_claim, _randomisation, _falsifiable, _confounds, _units,
           _agent_actions)


def _dataset_analysis_review(protocol: StudyProtocol) -> list[Finding]:
    """Checks that apply to an approved observational analysis plan."""
    found = [Finding("blocking", "completeness", problem)
             for problem in protocol.problems()]
    identity = protocol.dataset_identity or {}
    for field_name in ("source", "sha256", "layout_sha256"):
        if not identity.get(field_name):
            found.append(Finding("blocking", "dataset_identity",
                                 f"the audited dataset has no {field_name}"))
    tests = (protocol.analysis_plan or {}).get("tests") or []
    if not tests:
        found.append(Finding("blocking", "analysis_plan",
                             "the approved analysis plan contains no tests"))
    for test in tests:
        missing = [name for name in ("id", "block", "params", "compares",
                                     "support_if", "reject_if", "outputs")
                   if not test.get(name)]
        if missing:
            found.append(Finding(
                "blocking", "analysis_plan",
                f"test {test.get('id', '?')} is missing {', '.join(missing)}"))
        if test.get("support_if") == test.get("reject_if"):
            found.append(Finding("blocking", "falsifiability",
                                 f"test {test.get('id', '?')} uses the same support and reject rule"))
    if protocol.causal_claim:
        found.append(Finding(
            "blocking", "claim",
            "the deterministic declared-dataset path does not establish a causal claim"))
    return found


# --- the review ---------------------------------------------------------------------

def review(protocol: StudyProtocol, reviewer=None) -> Review:
    """
    Judge a design. `reviewer` is an optional model, used only to raise doubts.

    The protocol's own validity is checked first: a protocol missing required
    fields is not a design to be reviewed, it is an incomplete one.
    """
    if protocol.study_type is StudyType.DATASET_ANALYSIS:
        findings = _dataset_analysis_review(protocol)
    else:
        findings = [Finding("blocking", "completeness", problem)
                    for problem in protocol.problems()]
        for check in _CHECKS:
            findings.extend(check(protocol))

    verdict = FAIL if any(f.severity == "blocking" for f in findings) else PASS
    notes = ""
    if reviewer is not None and verdict == PASS:
        notes, doubts = _ask_a_reviewer(protocol, reviewer)
        findings.extend(doubts)
        if doubts:
            # A reviewer's doubt is a reason for a person to look, never a
            # reason to fail by itself -- and never a reason to pass.
            verdict = NEEDS_HUMAN
    if any(f.severity == "question" for f in findings) and verdict == PASS:
        verdict = PASS            # questions are recorded, not blocking
    return Review(verdict=verdict, findings=findings, reviewer_notes=notes)


_REVIEWER_SYSTEM = (
    "You are reviewing the methodology of an experiment before it is built. You are not "
    "deciding whether it is interesting. You are looking for reasons its results could "
    "not support the claim it makes: a confound nobody controlled, an outcome that does "
    "not measure the hypothesis, a comparison that changes more than one thing.\n\n"
    "Answer in JSON: {\"concerns\": [\"...\"], \"verdict\": \"ok\" | \"concerns\"}. "
    "List a concern only if you can say what specifically would go wrong. An empty list "
    "is the right answer for a sound design."
)


def _ask_a_reviewer(protocol: StudyProtocol, reviewer) -> tuple[str, list[Finding]]:
    """One model call, and only doubts are taken from it."""
    from router import TaskType

    prompt = ("Review this experimental design.\n\n" + protocol.to_json()
              + "\n\nWhat, specifically, could stop these results from supporting "
                "the claim?")
    try:
        raw = reviewer.generate(prompt=prompt, system=_REVIEWER_SYSTEM,
                                task_type=TaskType.QUALITY_REVIEW, max_tokens=1024,
                                temperature=0.0)
    except Exception as exc:
        logger.warning("The methodology reviewer could not be reached: %s", exc)
        return "", []
    try:
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        concerns = [str(c) for c in (data.get("concerns") or []) if str(c).strip()]
    except (ValueError, AttributeError):
        logger.warning("The methodology reviewer's answer could not be read.")
        return raw[:500], []
    return raw[:500], [Finding("question", "reviewer", c) for c in concerns[:5]]
