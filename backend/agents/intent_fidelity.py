"""
Does the protocol still say what was asked?

This is not the methodology review and must never be folded into it. They
answer different questions, and either can pass while the other fails:

    Intent fidelity   is this the study that was approved?
    Methodology       is this study sound?

A perfectly sound experiment about a different question is a scientific
failure, and it is the failure this whole system exists to prevent. It is also
the one that is hardest to see afterwards, because everything downstream
compares artifacts against the protocol -- so a protocol that has already
drifted is implemented faithfully, verified successfully, and wrong.

Five rules shape what is here.

**It is a monitor, not an author.** When it finds a mismatch it reports the
mismatch and blocks the freeze. It never edits the protocol to agree with the
question: a checker that rewrites what it checks has checked nothing.

**Deterministic mismatches are final.** A language model may be asked for
doubts, and a doubt can move PASS to NEEDS_HUMAN. Nothing it says can clear a
mismatch that was found by comparing identities.

**Not knowing is a verdict.** Where the approved intent cannot be mapped onto
the protocol, the answer is NEEDS_HUMAN rather than a guess in either
direction.

**The question is not the only authority.** What a person approved is ranked:
a structured approved intent first, then the approved hypothesis, then the
Research Question as framing, and the protocol never. A protocol keeping a
commitment that only the hypothesis stated has not drifted; a protocol
deciding something none of them stated has not been approved.

**Identity is compared, not wording.** Every scientific thing carries a
concept id (`agents/scientific_concepts.py`). `curation_condition` and
`curation_strategy` are one intervention; `target_selection_rate` and
`share_of_trials_selecting_target` are one outcome. Wording is compared only
as a fallback, when no identity is available on one of the two sides -- and
where identity is unavailable the gate says so rather than inferring sameness
from a shared prefix.

The comparison runs in both directions. Removing an approved commitment and
adding an unapproved one are both drift, and only the first of them used to be
visible.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents import scientific_concepts as sc

logger = logging.getLogger(__name__)

PASS, FAIL, NEEDS_HUMAN = "PASS", "FAIL", "NEEDS_HUMAN"
SUMMARY_FILE = "scientific_summary.md"

# Stable codes. They are counted across runs, so they do not get renamed.
INTERVENTION_CHANGED = "INTERVENTION_CHANGED"
CONDITION_DROPPED = "CONDITION_DROPPED"
COMPARATOR_CHANGED = "COMPARATOR_CHANGED"
PRIMARY_OUTCOME_CHANGED = "PRIMARY_OUTCOME_CHANGED"
SECONDARY_OUTCOME_DROPPED = "SECONDARY_OUTCOME_DROPPED"
HELD_CONSTANT_REMOVED = "HELD_CONSTANT_REMOVED"
STUDY_TYPE_CHANGED = "STUDY_TYPE_CHANGED"
UNIT_OF_ANALYSIS_CHANGED = "UNIT_OF_ANALYSIS_CHANGED"
CLAIM_SCOPE_EXPANDED = "CLAIM_SCOPE_EXPANDED"
CLAIM_SCOPE_WEAKENED = "CLAIM_SCOPE_WEAKENED"
REQUIRED_CONTROL_DROPPED = "REQUIRED_CONTROL_DROPPED"
AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
# A scientifically necessary choice that no approved source defines, which the
# protocol made anyway. Not a mismatch -- there is nothing to mismatch against
# -- and not permission either, so it is answered by a person.
INTENT_UNSPECIFIED = "INTENT_UNSPECIFIED"
# Two approved sources define the same thing differently. The higher rank is
# used for the comparison and the disagreement is still surfaced.
AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"

# --- added, not removed ---------------------------------------------------------------
# The direction the gate used to be blind in. An approved intent that
# enumerates its arms, its interventions or its outcomes is a closed list, and
# adding to a closed list is as much a change as taking from it.
CONDITION_ADDED = "CONDITION_ADDED"
INTERVENTION_ADDED = "INTERVENTION_ADDED"
OUTCOME_ADDED = "OUTCOME_ADDED"
CLAIM_DIRECTION_REVERSED = "CLAIM_DIRECTION_REVERSED"
PRESERVED_OUTCOME_VIOLATED = "PRESERVED_OUTCOME_VIOLATED"
# The same additions where the approval was prose rather than an enumeration.
# Prose does not promise to be exhaustive, so an addition to it is a question
# rather than a contradiction.
UNAPPROVED_ADDITION = "UNAPPROVED_ADDITION"
# An extra thing the study would have to show before its result counts.
SUCCESS_CRITERION_ADDED = "SUCCESS_CRITERION_ADDED"
# The approved side and the protocol side cannot both be given an identity, so
# there is nothing to compare. Not a mismatch: a mismatch needs two things that
# are known to differ. The cross-domain holdout of 2026-09-22 blocked ten of
# twelve faithful protocols this way, every one of them a rename the registry
# did not know, so an absent identity now asks a person instead of refusing.
IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
# The protocol claims the result holds beyond what it studied. Prose, not a
# protocol field, so it is never deterministic and always escalates.
CLAIM_SCOPE_GENERALISED = "CLAIM_SCOPE_GENERALISED"
# The protocol disagrees with itself about what it is testing.
CLAIM_INTERNALLY_INCONSISTENT = "CLAIM_INTERNALLY_INCONSISTENT"

_BLOCKING = {INTERVENTION_CHANGED, CONDITION_DROPPED, COMPARATOR_CHANGED,
             PRIMARY_OUTCOME_CHANGED, SECONDARY_OUTCOME_DROPPED, HELD_CONSTANT_REMOVED,
             STUDY_TYPE_CHANGED, UNIT_OF_ANALYSIS_CHANGED, CLAIM_SCOPE_EXPANDED,
             CLAIM_SCOPE_WEAKENED, REQUIRED_CONTROL_DROPPED,
             CONDITION_ADDED, INTERVENTION_ADDED, OUTCOME_ADDED,
             CLAIM_DIRECTION_REVERSED, PRESERVED_OUTCOME_VIOLATED}


@dataclass
class Finding:
    code: str
    detail: str
    approved_intent: str = ""
    protocol_says: str = ""

    @property
    def blocking(self) -> bool:
        return self.code in _BLOCKING

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail,
                "approved_intent": self.approved_intent, "protocol_says": self.protocol_says}


@dataclass
class Fidelity:
    status: str
    findings: list[Finding] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    reviewer_notes: str = ""
    # Which approved source each compared term was taken from, and which terms
    # no source supplied. A verdict nobody can trace back to an authority is
    # not reviewable, so the provenance travels with it.
    sources: dict = field(default_factory=dict)
    unspecified: list[str] = field(default_factory=list)
    # Every concept identity the comparison used, and where it came from:
    # carried from the approved intent, reconstructed from wording, or absent.
    concepts: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def failure_codes(self) -> list[str]:
        return sorted({f.code for f in self.findings if f.blocking})

    @property
    def needs_human_count(self) -> int:
        return sum(1 for f in self.findings if not f.blocking)

    def summary(self) -> str:
        if self.passed:
            return f"Intent fidelity passed ({len(self.checked)} comparisons)."
        first = self.findings[0]
        return f"Intent fidelity {self.status.lower()}: [{first.code}] {first.detail}"

    def as_dict(self) -> dict:
        return {"status": self.status, "checked": self.checked,
                "findings": [f.as_dict() for f in self.findings],
                "failure_codes": self.failure_codes,
                "needs_human_count": self.needs_human_count,
                "reviewer_notes": self.reviewer_notes,
                "intent_sources": self.sources, "unspecified": self.unspecified,
                "concepts": self.concepts}


# --- what was approved, and which part of it has authority ----------------------------
#
# The Research Question is not the whole of what a person approved, and that
# was the ambiguity the gate exposed the first time it ran: a short question
# names an intervention and an outcome, while the sentence that was actually
# signed off also names the comparator, what is held fixed, and what must not
# be harmed. Comparing a protocol against the question alone then reports
# drift for every commitment the question happened to leave out -- a false
# block on a protocol that was being faithful to the thing with authority.
#
# So the approved intent is kept in ranked pieces, and every term the checker
# compares against carries the rank it came from:
#
#     1  approved structured intent   what a person signed off, field by field
#     2  approved hypothesis          the approved sentence
#     3  research question            framing and context, not authority
#     4  the protocol                 never an authority; it is what is checked
#
# Two rules fall out of the ranking, and they pull in opposite directions on
# purpose:
#
#   * Where a higher rank defines something a lower rank omits, the higher
#     rank supplies it, and a protocol expressing it has not drifted.
#   * Where *no* rank defines a choice the protocol nonetheless made, that
#     choice was made downstream by something nobody approved. The answer is
#     NEEDS_HUMAN -- not PASS, because nobody approved it, and not FAIL,
#     because nobody forbade it either.
#
# Nothing here loosens a mismatch. Where an approved source does define a term
# and the protocol says something else, that is still a deterministic FAIL,
# and no ranking clears it.

STRUCTURED = "structured_intent"
HYPOTHESIS = "approved_hypothesis"
QUESTION = "research_question"
_PRECEDENCE = (STRUCTURED, HYPOTHESIS, QUESTION)

# The slots read out of each source.
_TUPLE_SLOTS = ("intervention", "conditions", "comparator", "primary_outcome",
                "secondary_outcomes", "held_constant", "preserved_outcomes")
_TEXT_SLOTS = ("direction", "unit")
_SLOTS = _TUPLE_SLOTS + _TEXT_SLOTS

# Which kind of concept each slot holds.
_SLOT_KIND = {"intervention": sc.INTERVENTION, "conditions": sc.CONDITION,
              "comparator": sc.CONDITION, "primary_outcome": sc.OUTCOME,
              "secondary_outcomes": sc.OUTCOME, "preserved_outcomes": sc.OUTCOME,
              "held_constant": sc.CONSTANT, "unit": sc.UNIT}

# The choices a controlled comparison cannot be run without. If one of these
# is defined by no approved source and the protocol has one anyway, it was
# decided downstream by something nobody approved.
NECESSARY_SLOTS = ("intervention", "conditions", "comparator", "primary_outcome",
                   "direction")

# Slots where two approved sources disagreeing is worth escalating, and the
# reason it is only these. Conditions, comparator and direction are read from
# closed vocabularies and from explicit markers, so a term appearing in one
# source and a different term in the other is a real disagreement. The outcome
# reader, by contrast, maps free prose onto concepts and can come up empty on a
# faithful paraphrase; calling that a conflict would report a disagreement
# nobody has. The higher authority governs the comparison either way, so the
# narrowing costs an escalation, never a mismatch.
_CONFLICT_SLOTS = ("conditions", "comparator", "direction", "held_constant")

# What a caller may write in an approved structured intent, and the slot each
# spelling means. Names people actually use, not a schema to be learnt.
_STRUCTURED_ALIASES = {
    "intervention": "intervention", "interventions": "intervention",
    "independent_variable": "intervention", "independent_variables": "intervention",
    "condition": "conditions", "conditions": "conditions", "arms": "conditions",
    "comparator": "comparator", "comparators": "comparator", "control": "comparator",
    "baseline": "comparator", "comparison_condition": "comparator",
    "primary_outcome": "primary_outcome", "primary_metric": "primary_outcome",
    "outcome": "primary_outcome",
    "secondary_outcomes": "secondary_outcomes", "secondary_outcome": "secondary_outcomes",
    "secondary_metrics": "secondary_outcomes",
    "held_constant": "held_constant", "held_fixed": "held_constant",
    "constants": "held_constant",
    "preserved_outcomes": "preserved_outcomes", "must_not_reduce": "preserved_outcomes",
    "direction": "direction", "effect_direction": "direction", "relation": "direction",
    "causality": "causality", "claim_type": "causality",
    "unit": "unit", "unit_of_analysis": "unit",
}

# Words people write for a relation, and the relation each one means. Approval
# is written by people, so "increases", "increase" and "higher" all have to
# arrive at the same place.
_FORM_WORDS = {
    "increase": sc.INCREASE, "increases": sc.INCREASE, "increased": sc.INCREASE,
    "higher": sc.INCREASE, "greater": sc.INCREASE, "up": sc.INCREASE,
    "decrease": sc.DECREASE, "decreases": sc.DECREASE, "decreased": sc.DECREASE,
    "lower": sc.DECREASE, "reduces": sc.DECREASE, "down": sc.DECREASE,
    "change": sc.TWO_SIDED, "changes": sc.TWO_SIDED, "differs": sc.TWO_SIDED,
    "difference": sc.TWO_SIDED, "two_sided": sc.TWO_SIDED, "two-sided": sc.TWO_SIDED,
    "unchanged": sc.EQUIVALENCE, "equivalence": sc.EQUIVALENCE,
    "no_effect": sc.EQUIVALENCE, "none": sc.EQUIVALENCE,
}


@dataclass(frozen=True)
class ApprovedIntent:
    """
    What a human approved, kept in ranked pieces rather than as one blob.

    `structured` is the highest authority: a mapping from a slot name to what
    was approved for it, written by whoever approved it. A value may be a
    display name, or a mapping that carries the scientific identity alongside
    it:

        {"primary_outcome": {"concept_id": "target_selection",
                             "display_name": "target selection rate"}}

    Carrying the id is what makes a later rename harmless. It is optional, and
    an empty structured intent is the ordinary case -- most studies are
    approved as a hypothesis sentence plus a question, and the ranking still
    applies.
    """
    hypothesis: str = ""
    research_question: str = ""
    structured: dict = field(default_factory=dict)
    approved_by: str = ""
    approved_at: str = ""
    # The field the approved terms should be read in. Left empty, it is taken
    # from the protocol's scaffold; where neither says, the domain is unknown
    # and only field-independent concepts may resolve.
    domain: str = ""

    @classmethod
    def from_protocol(cls, protocol) -> "ApprovedIntent":
        """
        The weakest honest reading: the protocol's own record of what it came
        from. Used when a caller supplies no approved intent. It is a
        fallback, not evidence that anybody approved anything.
        """
        return cls(hypothesis=getattr(protocol, "hypothesis", "") or "",
                   research_question=getattr(protocol, "research_question", "") or "")

    def as_dict(self) -> dict:
        return {"hypothesis": self.hypothesis, "research_question": self.research_question,
                "structured": dict(self.structured), "approved_by": self.approved_by,
                "approved_at": self.approved_at, "domain": self.domain}


# --- reading the intent out of the approved sources -----------------------------------

@dataclass
class StructuredIntent:
    """
    What the approved sources asked for, read literally and with provenance.

    Terms are kept as written, and their scientific identities are kept beside
    them in `concept_ids`. Where a source carried an id, that id is used;
    where it did not, the id is reconstructed from the wording and recorded as
    reconstructed, so a later reader can tell a carried identity from a
    reconstructed one.
    """
    research_question: str
    hypothesis: str
    intervention_terms: tuple[str, ...] = ()
    condition_terms: tuple[str, ...] = ()
    comparator_terms: tuple[str, ...] = ()
    primary_outcome_terms: tuple[str, ...] = ()
    secondary_outcome_terms: tuple[str, ...] = ()
    held_constant_terms: tuple[str, ...] = ()
    direction: str = ""              # a relation form from scientific_concepts
    preserved_outcomes: tuple[str, ...] = ()   # "without reducing X"
    unit: str = ""
    ambiguous: tuple[str, ...] = ()
    sources: dict = field(default_factory=dict)      # slot -> rank it came from
    unspecified: tuple[str, ...] = ()                # slots no source defines
    conflicts: tuple[str, ...] = ()                  # slots two sources disagree on
    concept_ids: dict = field(default_factory=dict)  # slot -> tuple of concept ids
    concept_sources: dict = field(default_factory=dict)   # slot -> how it was obtained
    relation: sc.Relation = field(default_factory=sc.Relation)

    def source_of(self, slot: str) -> str:
        return self.sources.get(slot, "")

    def defines(self, slot: str) -> bool:
        return slot not in self.unspecified

    def enumerated(self, slot: str) -> bool:
        """Whether the approval for this slot is a closed list rather than prose."""
        return self.sources.get(slot) == STRUCTURED

    def concepts(self, slot: str) -> tuple[str, ...]:
        return tuple(self.concept_ids.get(slot, ()))

    def as_dict(self) -> dict:
        out = {}
        for key, value in self.__dict__.items():
            if isinstance(value, sc.Relation):
                out[key] = value.as_dict()
            else:
                out[key] = list(value) if isinstance(value, tuple) else value
        return out


_HELD = re.compile(r"\b(?:holding|with|keeping|given)\s+(?:the\s+)?([\w\s-]{3,40}?)\s+"
                   r"(?:fixed|constant|unchanged|identical)\b", re.I)
_HELD_ALT = re.compile(r"\b(?:on|from|against)\s+(?:a\s+|the\s+)?"
                       r"(?:fixed|frozen|identical|same)\s+([\w\s-]{3,30})", re.I)


def _read_text(text: str, domain: str = "") -> dict:
    """
    Read one approved source on its own.

    Each source is read separately and never concatenated with another. A
    concatenation loses which of them said what, and which of them said it is
    the whole question here.

    Outcomes and their relations are read clause by clause. Taking the first
    direction word in a sentence is what made "increases selection without
    reducing approval" into a claim that something decreases.
    """
    text = str(text or "").strip()
    if not text:
        return {}
    found: dict = {}

    # -- outcomes, and what is claimed about each -------------------------
    primary: list[str] = []
    preserved: list[str] = []
    others: list[str] = []
    relation = sc.Relation()
    for clause in sc.clauses(text):
        outcome = sc.resolve(clause, sc.OUTCOME, domain)
        if not outcome:
            continue
        clause_relation = sc.relation_for(clause, outcome, domain)
        if clause_relation.form in (sc.INCREASE, sc.DECREASE, sc.TWO_SIDED):
            if not primary:
                primary.append(outcome)
                relation = clause_relation
            elif outcome not in primary and outcome not in others:
                others.append(outcome)
        elif clause_relation.form == sc.EQUIVALENCE:
            if outcome not in preserved:
                preserved.append(outcome)
        elif outcome not in others:
            others.append(outcome)
    if not primary:
        # Something is named but nothing is claimed about it. That is not a
        # primary outcome; it is a list, and it is reported as one.
        others = list(dict.fromkeys(preserved + others))
        preserved = []
    if primary:
        found["primary_outcome"] = tuple(primary)
        found["direction"] = relation.form
        found["relation"] = relation
    if preserved:
        found["preserved_outcomes"] = tuple(preserved)
    if others:
        found["secondary_outcomes"] = tuple(others)

    # -- conditions and the comparator ------------------------------------
    words = sc.lemmas(text)
    conditions = tuple(c.concept_id for c in sc.REGISTRY
                       if c.kind == sc.CONDITION and c.visible_in(domain)
                       and c.matches(words))
    if len(conditions) >= 2:
        found["conditions"] = conditions
        comparator = tuple(c for c in conditions
                           if c in ("benign_curation", "control_condition",
                                    "neutral_curation", "full_pool_presentation"))
        if comparator:
            found["comparator"] = comparator

    # -- what is held fixed -----------------------------------------------
    candidates = [m.group(1).strip().lower() for m in _HELD.finditer(text)]
    candidates += [m.group(1).strip().lower() for m in _HELD_ALT.finditer(text)]
    held = []
    for candidate in dict.fromkeys(c for c in candidates if c):
        # "with its explicit approval unchanged" is the same grammar as
        # "with the candidate pool fixed" and means something different: an
        # outcome that must not move is a preserved outcome, not a nuisance
        # variable held constant, and filing it as a constant makes the two
        # approved sources look like they disagree.
        as_outcome = sc.resolve(candidate, sc.OUTCOME, domain)
        if as_outcome:
            if as_outcome not in preserved and as_outcome not in primary:
                preserved.append(as_outcome)
                found["preserved_outcomes"] = tuple(preserved)
            continue
        held.append(candidate)
    if held:
        found["held_constant"] = tuple(held)

    # -- the intervention --------------------------------------------------
    interventions = tuple(c.concept_id for c in sc.REGISTRY
                          if c.kind == sc.INTERVENTION and c.visible_in(domain)
                          and c.matches(words))
    if interventions:
        found["intervention"] = interventions

    # -- the unit of analysis ----------------------------------------------
    unit = re.search(r"\bper\s+(trial|participant|session|item|task|episode|block)\b",
                     text.lower())
    if unit:
        found["unit"] = unit.group(1)
    return found


def _structured_entry(value) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    One structured value, split into the names written and the ids carried.

    A caller may write a plain string, a mapping with a concept id, or a list
    mixing both. All three arrive here and leave as (display names, concept ids).
    """
    items = value if isinstance(value, (list, tuple)) else (value,)
    names: list[str] = []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict):
            concept_id = str(item.get("concept_id") or "").strip()
            display = str(item.get("display_name") or item.get("name") or concept_id).strip()
            if concept_id:
                ids.append(concept_id)
            if display:
                names.append(display)
        elif str(item).strip():
            names.append(str(item).strip())
    return tuple(names), tuple(ids)


def _read_structured(structured: dict) -> tuple[dict, dict]:
    """Read the approved structured intent, which says what it means directly."""
    found: dict = {}
    ids: dict = {}
    for key, value in (structured or {}).items():
        slot = _STRUCTURED_ALIASES.get(str(key).strip().lower())
        if not slot or value in (None, "", (), []):
            continue
        names, concept_ids = _structured_entry(value)
        if slot == "direction":
            word = (names[0] if names else "").strip().lower()
            found[slot] = _FORM_WORDS.get(word, word)
            continue
        if slot == "unit":
            pick = (concept_ids or names)
            if pick:
                found[slot] = pick[0].strip().lower()
                if concept_ids:
                    ids[slot] = concept_ids
            continue
        if names:
            found[slot] = names
        if concept_ids:
            ids[slot] = concept_ids
    return found, ids


# --- resolving the sources against each other -----------------------------------------

def _normalise(term: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(term).strip().lower())


def _conflicting(first, second) -> bool:
    """
    Whether two sources say different things about the same slot.

    An omission is not a conflict, and a subset is not a conflict: a short
    question naming one arm of a two-arm comparison is the ordinary case, and
    treating that as disagreement would recreate the false block this ranking
    exists to remove. Only genuinely incompatible values count.
    """
    if isinstance(first, str) or isinstance(second, str):
        return bool(first) and bool(second) and first != second
    a = {_normalise(x) for x in first}
    b = {_normalise(x) for x in second}

    def covered(one, other) -> bool:
        # A source may say "curation" where an approved structured intent says
        # "curation_condition". Those are the same commitment written at two
        # levels of detail, and calling them a conflict would report a
        # disagreement that nobody has.
        return all(any(x == y or x in y or y in x for y in other) for x in one)

    return not (covered(a, b) or covered(b, a))


_UNSTATED = {
    "direction": "no approved source states a relation between the intervention "
                 "and the outcome",
    "conditions": "no approved source names two conditions to compare",
    "comparator": "no approved source names what the comparison is against",
    "primary_outcome": "no approved source names the outcome",
    "intervention": "no approved source names what is intervened on",
}


def _shown(value) -> str:
    return value if isinstance(value, str) else ", ".join(value)


def read_intent(research_question: str = "", hypothesis: str = "",
                structured: dict | None = None,
                approved: ApprovedIntent | None = None,
                domain: str = "") -> StructuredIntent:
    """
    Read the approved intent literally, highest authority first.

    The three sources are read separately and then resolved in precedence
    order. Nothing is inferred to fill a gap: a slot no source defines is
    recorded as unspecified, which is a verdict of its own.
    """
    if approved is None:
        approved = ApprovedIntent(hypothesis=hypothesis,
                                  research_question=research_question,
                                  structured=structured or {})
    domain = domain or approved.domain
    structured_reading, carried_ids = _read_structured(approved.structured)
    readings = {
        STRUCTURED: structured_reading,
        HYPOTHESIS: _read_text(approved.hypothesis, domain),
        QUESTION: _read_text(approved.research_question, domain),
    }

    resolved: dict = {}
    sources: dict = {}
    unspecified: list[str] = []
    for slot in _SLOTS:
        for rank in _PRECEDENCE:
            if readings[rank].get(slot):
                resolved[slot] = readings[rank][slot]
                sources[slot] = rank
                break
        else:
            resolved[slot] = "" if slot in _TEXT_SLOTS else ()
            unspecified.append(slot)

    relation = sc.Relation(form=resolved["direction"] or sc.UNSPECIFIED)
    picked = sources.get("direction")
    if picked and isinstance(readings[picked].get("relation"), sc.Relation):
        relation = readings[picked]["relation"]
    # Whether the approval claims a cause or an association is resolved on its
    # own, in the same precedence order. It is not a property of the direction
    # and must not be lost because the direction came from a structured field
    # while the causal wording lives in the approved sentence.
    stated_causality = str((approved.structured or {}).get("causality")
                           or (approved.structured or {}).get("claim_type")
                           or "").strip().lower()
    causal = stated_causality if stated_causality in (sc.CAUSAL, sc.ASSOCIATIONAL) else ""
    for text in (approved.hypothesis, approved.research_question):
        if causal:
            break
        found_causal = sc.causality(text)
        if found_causal != sc.UNSTATED:
            causal = found_causal
    relation = sc.Relation(form=relation.form, causal=causal or sc.UNSTATED,
                           anchored=relation.anchored, evidence=relation.evidence)

    # Identity for each slot: carried where a source carried it, reconstructed
    # from wording otherwise, absent where neither is possible.
    concept_ids: dict = {}
    concept_sources: dict = {}
    for slot in _TUPLE_SLOTS + ("unit",):
        kind = _SLOT_KIND.get(slot)
        if carried_ids.get(slot) and sources.get(slot) == STRUCTURED:
            concept_ids[slot] = tuple(carried_ids[slot])
            concept_sources[slot] = sc.FROM_APPROVED
            continue
        terms = resolved.get(slot) or ()
        terms = (terms,) if isinstance(terms, str) else tuple(terms)
        if not terms:
            continue
        # A text source already yields concept ids for outcomes, conditions and
        # interventions; only free phrases have to be resolved.
        known = tuple(t for t in terms if sc.concept(t))
        if len(known) == len(terms):
            concept_ids[slot] = known
            concept_sources[slot] = (sc.FROM_APPROVED if sources.get(slot) == STRUCTURED
                                     else sc.FROM_REGISTRY)
            continue
        found, missed = sc.resolve_all(terms, kind, domain)
        if found:
            concept_ids[slot] = found
            concept_sources[slot] = sc.FROM_REGISTRY
        if missed:
            concept_sources.setdefault(slot, sc.UNRESOLVED)

    conflicts: list[str] = []
    for slot in _CONFLICT_SLOTS:
        stated = [(rank, readings[rank][slot])
                  for rank in _PRECEDENCE if readings[rank].get(slot)]
        for lower, higher in zip(stated, stated[1:]):
            if _conflicting(lower[1], higher[1]):
                conflicts.append(
                    f"{slot}: the {lower[0].replace('_', ' ')} says {_shown(lower[1])} "
                    f"and the {higher[0].replace('_', ' ')} says {_shown(higher[1])}; "
                    "the higher authority was used")
                break

    # Only a necessary choice that nobody stated is worth a note here, and only
    # the one the checker has no more concrete thing to say about: the others
    # are reported downstream against the value the protocol invented for them.
    ambiguous = [_UNSTATED[slot] for slot in ("conditions",) if slot in unspecified]

    return StructuredIntent(
        research_question=approved.research_question, hypothesis=approved.hypothesis,
        intervention_terms=tuple(resolved["intervention"]),
        condition_terms=tuple(resolved["conditions"]),
        comparator_terms=tuple(resolved["comparator"]),
        primary_outcome_terms=tuple(resolved["primary_outcome"]),
        secondary_outcome_terms=tuple(resolved["secondary_outcomes"]),
        held_constant_terms=tuple(resolved["held_constant"]),
        direction=resolved["direction"],
        preserved_outcomes=tuple(resolved["preserved_outcomes"]), unit=resolved["unit"],
        ambiguous=tuple(ambiguous), sources=sources, unspecified=tuple(unspecified),
        conflicts=tuple(conflicts), concept_ids=concept_ids,
        concept_sources=concept_sources, relation=relation)


# --- comparing identities -------------------------------------------------------------

_FILLER = {"the", "a", "an", "of", "in", "on", "for", "its", "their", "this", "that",
           "underlying", "overall", "same", "given", "each", "every", "some", "any"}


def _content_words(term: str) -> set[str]:
    """The words in a term that carry its meaning. Only used by the fallback."""
    words = re.split(r"[\s_\-/]+", term.lower())
    return {w.rstrip("s") for w in words if len(w) > 3 and w not in _FILLER}


def _mentions(haystack, term: str) -> bool:
    """
    Whether a protocol field expresses the same term the approval used.

    The fallback, kept deliberately unchanged: it is what the gate falls back
    to when identity is unavailable, and softening it would weaken a
    deterministic check to buy nothing.
    """
    wanted = _content_words(term)
    if not wanted:
        return True                       # nothing to match on: not a mismatch
    text = haystack.lower() if isinstance(haystack, str) else " ".join(
        str(item).lower() for item in haystack)
    present = _content_words(text)
    return (all(any(word == p or word in p or p in word for p in present)
                for word in wanted) if len(wanted) <= 2
            else len(wanted & present) >= max(1, len(wanted) - 1))


def _protocol_concepts(protocol, values, kind,
                       domain: str = "") -> tuple[dict, tuple[str, ...]]:
    """
    The identities a protocol's field values carry, and the values that carry none.

    A protocol may propagate identity explicitly through `concepts`, keyed by
    the display name it uses. Where it does, that id is authoritative and a
    rename costs nothing. Where it does not, the id is reconstructed from the
    wording, and where that fails the value is returned as unresolved rather
    than assumed to be anything.
    """
    carried = getattr(protocol, "concepts", None) or {}
    provenance = getattr(protocol, "concept_provenance", None) or {}
    found: dict = {}
    missed: list[str] = []
    values = (values,) if isinstance(values, str) else (values or ())
    for value in values:
        value = str(value)
        if not value.strip():
            continue
        if carried.get(value):
            found[carried[value]] = (value, provenance.get(value, sc.FROM_APPROVED))
            continue
        concept_id = sc.resolve(value, kind, domain)
        if concept_id:
            found.setdefault(concept_id, (value, sc.FROM_REGISTRY))
        else:
            missed.append(value)
    return found, tuple(missed)


def _display(protocol_concepts: dict, concept_id: str) -> str:
    entry = protocol_concepts.get(concept_id)
    return entry[0] if entry else ""



def _unmatched(slot: str, kind: str, concept_id: str, approved_label: str,
               protocol_values, unresolved, blocking_code: str, detail: str,
               domain: str = "") -> Finding:
    """
    What to say when an approved concept is not among the protocol's.

    Three situations wear the same shape. If every value the protocol uses has
    an identity and none of them is this one, the protocol is doing something
    else: a deterministic contradiction. If a value has no identity in this
    field but resolves unambiguously in another, the study has changed field,
    which is also a contradiction and is the original incident -- a choice-set
    study rebuilt as reinforcement learning. If a value has no identity
    anywhere that can be trusted, nothing has been contradicted: the gate
    cannot tell, and saying FAIL there is how a faithful rename became a block.
    """
    for value in unresolved or ():
        foreign, other = sc.resolve_foreign(value, kind, domain)
        if foreign:
            return Finding(
                blocking_code,
                f"{detail}. {value} is not a {domain.replace(chr(95), chr(32))} term at "
                f"all: it names {sc.label(foreign)}, which belongs to "
                f"{other.replace(chr(95), chr(32))}",
                approved_label, ", ".join(str(v) for v in protocol_values))
    if unresolved:
        return Finding(
            IDENTITY_UNRESOLVED,
            f"the approved intent names {approved_label} as the {slot}, and "
            f"{chr(44).join(unresolved)} could not be given a scientific identity, so "
            "whether they are the same thing cannot be decided here",
            approved_label, ", ".join(str(v) for v in protocol_values))
    return Finding(blocking_code, detail, approved_label,
                   ", ".join(str(v) for v in protocol_values))

def _check_dataset_analysis(protocol, approved: ApprovedIntent) -> Fidelity:
    """Exact authority comparison for a human-approved analysis plan."""
    findings: list[Finding] = []
    checked = ["research question", "approved hypotheses", "dataset identity",
               "analysis plan", "primary outcome", "variables"]
    structured = approved.structured or {}

    if protocol.research_question.strip() != approved.research_question.strip():
        findings.append(Finding(
            CLAIM_SCOPE_EXPANDED,
            "the protocol's research question is not the question that was approved",
            approved.research_question, protocol.research_question))
    if protocol.hypothesis.strip() != approved.hypothesis.strip():
        findings.append(Finding(
            CLAIM_SCOPE_EXPANDED,
            "the protocol's selected hypotheses are not the hypotheses that were approved",
            approved.hypothesis, protocol.hypothesis))
    if not structured.get("dataset_identity") or not structured.get("analysis_plan"):
        findings.append(Finding(
            INTENT_UNSPECIFIED,
            "the approval does not carry the audited dataset and approved analysis plan"))
    else:
        if protocol.dataset_identity != structured["dataset_identity"]:
            findings.append(Finding(
                INTERVENTION_CHANGED,
                "the protocol is bound to a different dataset than the approved audit",
                json.dumps(structured["dataset_identity"], sort_keys=True),
                json.dumps(protocol.dataset_identity, sort_keys=True)))
        if protocol.analysis_plan != structured["analysis_plan"]:
            findings.append(Finding(
                REQUIRED_CONTROL_DROPPED,
                "the protocol's tests differ from the human-approved analysis plan",
                json.dumps(structured["analysis_plan"], sort_keys=True),
                json.dumps(protocol.analysis_plan, sort_keys=True)))

    def displays(value) -> tuple[str, ...]:
        values = value if isinstance(value, (list, tuple)) else (value,)
        return tuple(str(v.get("display_name") or v.get("name") or "")
                     if isinstance(v, dict) else str(v) for v in values if v)

    approved_primary = displays(structured.get("primary_outcome"))
    if approved_primary and protocol.primary_metric not in approved_primary:
        findings.append(Finding(
            PRIMARY_OUTCOME_CHANGED,
            "the protocol's primary outcome differs from the approved analysis output",
            ", ".join(approved_primary), protocol.primary_metric))
    approved_variables = set(displays(structured.get("interventions") or ()))
    if approved_variables and set(protocol.independent_variables) != approved_variables:
        findings.append(Finding(
            INTERVENTION_CHANGED,
            "the protocol's variable bindings differ from the approved analysis plan",
            ", ".join(sorted(approved_variables)),
            ", ".join(sorted(protocol.independent_variables))))

    blocking = [finding for finding in findings if finding.blocking]
    status = FAIL if blocking else NEEDS_HUMAN if findings else PASS
    return Fidelity(status=status, findings=findings, checked=checked,
                    sources={name: STRUCTURED for name in checked},
                    unspecified=[] if not findings else ["dataset_analysis_authority"])


def check(protocol, intent: StructuredIntent | None = None, reviewer=None,
          approved: ApprovedIntent | None = None) -> Fidelity:
    """
    Compare the protocol against the intent that was approved.

    `approved` is the ranked record of what a person signed off. When it is
    not given, the protocol's own question and hypothesis stand in for it --
    which is weaker, and is why a caller that has a real approval should pass
    one.

    Returns PASS, FAIL or NEEDS_HUMAN. It never changes the protocol.
    """
    approved = approved or ApprovedIntent.from_protocol(protocol)
    # A declared-dataset plan is already structured authority: the user
    # approved exact TEST blocks after their variables were checked against the
    # audit.  Reducing that record back to prose would discard the very
    # identities this gate must protect, so this family compares the approved
    # records directly inside the same authoritative fidelity implementation.
    from agents.study_protocol import StudyType
    if protocol.study_type is StudyType.DATASET_ANALYSIS:
        return _check_dataset_analysis(protocol, approved)
    # The field these terms are read in. The approval may state it; otherwise
    # it follows from the scaffold that implements the study. When neither
    # says, it stays unknown, and only field-independent concepts resolve.
    domain = approved.domain or sc.domain_of(protocol)
    intent = intent or read_intent(approved=approved, domain=domain)
    findings: list[Finding] = []
    checked: list[str] = []
    seen: dict = {}

    if not (approved.research_question.strip() or approved.hypothesis.strip()
            or approved.structured):
        return Fidelity(FAIL, [Finding(AMBIGUOUS_MAPPING,
                                       "no approved intent was recorded to compare against")])

    def record(slot, approved_ids, protocol_side, unresolved):
        seen[slot] = {
            "approved": list(approved_ids),
            "approved_identity": intent.concept_sources.get(slot, sc.UNRESOLVED),
            "protocol": {cid: {"display": display, "identity": how}
                         for cid, (display, how) in protocol_side.items()},
            "protocol_unresolved": list(unresolved),
        }

    def added_code(slot, blocking_code):
        """Enumerated approvals are closed lists; prose is not."""
        return blocking_code if intent.enumerated(slot) else UNAPPROVED_ADDITION

    # -- intervention --------------------------------------------------------
    checked.append("intervention")
    approved_interventions = intent.concepts("intervention")
    protocol_interventions, unresolved_iv = _protocol_concepts(
        protocol, protocol.independent_variables, sc.INTERVENTION, domain)
    record("intervention", approved_interventions, protocol_interventions, unresolved_iv)
    if approved_interventions:
        for concept_id in approved_interventions:
            if concept_id in protocol_interventions:
                continue
            if unresolved_iv and _mentions(unresolved_iv, concept_id):
                continue                      # no identity; the wording still agrees
            if _mentions(protocol.conditions, concept_id):
                continue                      # varied through the arms themselves
            findings.append(_unmatched(
                "intervention", sc.INTERVENTION, concept_id, sc.label(concept_id),
                protocol.independent_variables, unresolved_iv, INTERVENTION_CHANGED,
                f"the approved intent intervenes on {sc.label(concept_id)}; the protocol "
                f"varies {', '.join(protocol.independent_variables)}", domain))
        for concept_id in protocol_interventions:
            if concept_id not in approved_interventions:
                findings.append(Finding(
                    added_code("intervention", INTERVENTION_ADDED),
                    f"the protocol varies {_display(protocol_interventions, concept_id)}, "
                    "which no approved source names as an intervention",
                    ", ".join(sc.label(c) for c in approved_interventions),
                    _display(protocol_interventions, concept_id)))
    elif intent.intervention_terms and not any(
            _mentions(protocol.independent_variables, term) or
            _mentions(protocol.conditions, term) for term in intent.intervention_terms):
        findings.append(Finding(
            INTERVENTION_CHANGED,
            f"the approved intent intervenes on {', '.join(intent.intervention_terms)}; "
            f"the protocol varies {', '.join(protocol.independent_variables)}",
            ", ".join(intent.intervention_terms), ", ".join(protocol.independent_variables)))

    # -- conditions ----------------------------------------------------------
    checked.append("conditions")
    approved_conditions = intent.concepts("conditions")
    protocol_conditions, unresolved_cond = _protocol_concepts(
        protocol, protocol.conditions, sc.CONDITION, domain)
    record("conditions", approved_conditions, protocol_conditions, unresolved_cond)
    if approved_conditions:
        for concept_id in approved_conditions:
            if concept_id in protocol_conditions:
                continue
            if unresolved_cond and _mentions(unresolved_cond, concept_id):
                continue
            findings.append(_unmatched(
                "condition", sc.CONDITION, concept_id, sc.label(concept_id),
                protocol.conditions, unresolved_cond, CONDITION_DROPPED,
                f"the approved intent names a {sc.label(concept_id)} condition; the "
                f"protocol's conditions are {', '.join(protocol.conditions)}", domain))
    else:
        for term in intent.condition_terms:
            if not _mentions(protocol.conditions, term):
                findings.append(Finding(
                    CONDITION_DROPPED,
                    f"the approved intent names a {term} condition; the protocol's "
                    f"conditions are {', '.join(protocol.conditions)}",
                    term, ", ".join(protocol.conditions)))

    checked.append("conditions added")
    if approved_conditions:
        added = [c for c in protocol_conditions if c not in approved_conditions]
        for concept_id in added:
            findings.append(Finding(
                added_code("conditions", CONDITION_ADDED),
                f"the protocol has a {_display(protocol_conditions, concept_id)} arm, "
                "which no approved source names",
                ", ".join(sc.label(c) for c in approved_conditions),
                _display(protocol_conditions, concept_id)))
        # An approved arm split into several is an addition even when every
        # approved identity is still present: the approved contrast is gone.
        if not added and len(protocol.conditions) > len(approved_conditions):
            findings.append(Finding(
                added_code("conditions", CONDITION_ADDED),
                f"the approved intent compares {len(approved_conditions)} conditions and "
                f"the protocol has {len(protocol.conditions)} "
                f"({', '.join(protocol.conditions)}); an approved arm has been split or "
                "an extra one added",
                ", ".join(sc.label(c) for c in approved_conditions),
                ", ".join(protocol.conditions)))

    checked.append("comparator")
    approved_comparators = intent.concepts("comparator")
    if approved_comparators:
        if not any(c in protocol_conditions for c in approved_comparators) and not (
                unresolved_cond and any(_mentions(unresolved_cond, c)
                                        for c in approved_comparators)):
            findings.append(_unmatched(
                "comparator", sc.CONDITION, approved_comparators[0],
                ", ".join(sc.label(c) for c in approved_comparators),
                protocol.conditions, unresolved_cond, COMPARATOR_CHANGED,
                "the comparison is against "
                f"{', '.join(sc.label(c) for c in approved_comparators)}, which the "
                "protocol does not have", domain))
    elif intent.comparator_terms and not any(
            _mentions(protocol.conditions, term) for term in intent.comparator_terms):
        findings.append(Finding(
            COMPARATOR_CHANGED,
            f"the comparison is against {', '.join(intent.comparator_terms)}, which the "
            "protocol does not have", ", ".join(intent.comparator_terms),
            ", ".join(protocol.conditions)))

    # -- outcomes ------------------------------------------------------------
    checked.append("primary outcome")
    approved_primary = intent.concepts("primary_outcome")
    protocol_primary, unresolved_primary = _protocol_concepts(
        protocol, (protocol.primary_metric,), sc.OUTCOME, domain)
    record("primary_outcome", approved_primary, protocol_primary, unresolved_primary)
    primary_id = next(iter(protocol_primary), "")
    if approved_primary and primary_id:
        if primary_id not in approved_primary:
            findings.append(Finding(
                PRIMARY_OUTCOME_CHANGED,
                f"the approved intent is about {sc.label(approved_primary[0])}; the "
                f"primary outcome is {protocol.primary_metric}",
                sc.label(approved_primary[0]), protocol.primary_metric))
    elif approved_primary:
        # The protocol's outcome has no identity in this field. If it has one
        # in another field the study has changed field, which is a
        # contradiction. Otherwise nothing has been contradicted and the
        # honest answer is that this cannot be decided here.
        foreign, other = sc.resolve_foreign(protocol.primary_metric, sc.OUTCOME, domain)
        for concept_id in approved_primary:
            same = (_mentions(protocol.primary_metric, sc.label(concept_id))
                    or _mentions(protocol.primary_metric, concept_id))
            if same:
                continue
            if foreign:
                findings.append(Finding(
                    PRIMARY_OUTCOME_CHANGED,
                    f"the approved intent is about {sc.label(concept_id)}; the protocol "
                    f"measures {protocol.primary_metric}, which names "
                    f"{sc.label(foreign)} and belongs to "
                    f"{other.replace(chr(95), chr(32))}, not to this study",
                    sc.label(concept_id), protocol.primary_metric))
                continue
            findings.append(Finding(
                IDENTITY_UNRESOLVED,
                f"the approved intent measures {sc.label(concept_id)}; the protocol "
                f"measures {protocol.primary_metric}, which could not be given a "
                "scientific identity, so whether they are the same outcome cannot be "
                "decided here", sc.label(concept_id), protocol.primary_metric))
    else:
        for term in intent.primary_outcome_terms:
            if not _mentions(protocol.primary_metric, term):
                findings.append(Finding(
                    PRIMARY_OUTCOME_CHANGED,
                    f"the approved intent is about {term}; the primary outcome is "
                    f"{protocol.primary_metric}", term, protocol.primary_metric))

    checked.append("secondary outcomes")
    measures = (protocol.primary_metric,) + tuple(protocol.secondary_metrics)
    protocol_measured, unresolved_measured = _protocol_concepts(
        protocol, measures, sc.OUTCOME, domain)
    wanted_secondary = tuple(dict.fromkeys(
        intent.concepts("secondary_outcomes") + intent.concepts("preserved_outcomes")))
    record("secondary_outcomes", wanted_secondary, protocol_measured, unresolved_measured)
    if wanted_secondary:
        for concept_id in wanted_secondary:
            if concept_id in protocol_measured:
                continue
            if unresolved_measured and _mentions(unresolved_measured, sc.label(concept_id)):
                continue
            findings.append(_unmatched(
                "secondary outcome", sc.OUTCOME, concept_id, sc.label(concept_id),
                measures, unresolved_measured, SECONDARY_OUTCOME_DROPPED,
                f"the approved intent speaks about {sc.label(concept_id)} and no outcome "
                "measures it", domain))
    else:
        for term in tuple(intent.secondary_outcome_terms) + tuple(intent.preserved_outcomes):
            if not any(_mentions(m, term) for m in measures):
                findings.append(Finding(
                    SECONDARY_OUTCOME_DROPPED,
                    f"the approved intent speaks about {term} and no outcome measures it",
                    term, ", ".join(measures)))

    # -- held constant -------------------------------------------------------
    checked.append("held constant")
    approved_constants = intent.concepts("held_constant")
    protocol_constants, unresolved_constants = _protocol_concepts(
        protocol, protocol.held_constant, sc.CONSTANT, domain)
    record("held_constant", approved_constants, protocol_constants, unresolved_constants)
    if approved_constants:
        for concept_id in approved_constants:
            if concept_id in protocol_constants:
                continue
            if unresolved_constants and _mentions(unresolved_constants, concept_id):
                continue
            findings.append(_unmatched(
                "held constant", sc.CONSTANT, concept_id, sc.label(concept_id),
                protocol.held_constant, unresolved_constants, HELD_CONSTANT_REMOVED,
                f"the approved intent holds {sc.label(concept_id)} fixed; the protocol "
                f"holds {', '.join(protocol.held_constant) or 'nothing'} constant", domain))
    else:
        for term in intent.held_constant_terms:
            if not _mentions(protocol.held_constant, term):
                findings.append(Finding(
                    HELD_CONSTANT_REMOVED,
                    f"the approved intent holds {term} fixed; the protocol holds "
                    f"{', '.join(protocol.held_constant) or 'nothing'} constant",
                    term, ", ".join(protocol.held_constant)))

    # -- the strength of the claim -------------------------------------------
    checked.append("claim scope")
    findings.extend(_claim_scope(intent, protocol, approved_primary, primary_id,
                                 domain))

    # -- does the protocol agree with itself? --------------------------------
    checked.append("internal consistency")
    findings.extend(_internal_consistency(protocol, primary_id or
                                          (approved_primary[0] if approved_primary else ""),
                                          domain))

    # -- does it claim more ground than it studied? --------------------------
    checked.append("claim generality")
    findings.extend(_generality(intent, protocol))

    # -- what the protocol would have to show --------------------------------
    checked.append("success criteria")
    findings.extend(_criteria(intent, protocol, approved_primary, wanted_secondary,
                              domain))

    # -- controls the approval implies ---------------------------------------
    checked.append("required controls")
    if (intent.held_constant_terms or approved_constants) and not protocol.required_controls:
        findings.append(Finding(
            REQUIRED_CONTROL_DROPPED,
            "the approved intent holds something fixed and the protocol names no controls",
            ", ".join(intent.held_constant_terms) or
            ", ".join(sc.label(c) for c in approved_constants), "none"))

    # -- unit of analysis ----------------------------------------------------
    checked.append("unit of analysis")
    findings.extend(_unit(intent, protocol, seen, domain))

    # -- choices nobody approved ----------------------------------------------
    # The other half of the precedence rule. Where an approved source defines
    # something, the protocol is held to it above. Where none of them does and
    # the protocol decided anyway, the decision was made downstream -- so it is
    # named, with the value that was invented, and a person answers it.
    checked.append("unapproved decisions")
    findings.extend(_invented_downstream(intent, protocol))

    # -- approved sources that disagree with each other ------------------------
    checked.append("authority conflicts")
    for note in intent.conflicts:
        findings.append(Finding(AUTHORITY_CONFLICT, note))

    # -- things that could not be read ---------------------------------------
    for note in intent.ambiguous:
        findings.append(Finding(AMBIGUOUS_MAPPING, note))

    status = FAIL if any(f.blocking for f in findings) else (
        NEEDS_HUMAN if findings else PASS)

    notes = ""
    if reviewer is not None and status == PASS:
        notes, doubts = _ask_a_reviewer(intent, protocol, reviewer)
        findings.extend(doubts)
        if doubts:
            status = NEEDS_HUMAN            # a doubt can raise the bar, never lower it
    return Fidelity(status=status, findings=findings, checked=checked, reviewer_notes=notes,
                    sources=dict(intent.sources), unspecified=list(intent.unspecified),
                    concepts=seen)


# --- the pieces of the comparison -----------------------------------------------------

# The claim fields, in the order the protocol's commitment is read from them.
# The criterion that would decide the result is read before the prose that
# describes it: a protocol whose support condition says "higher" is testing a
# direction whatever its narrative paragraph says, and one whose support
# condition says "differs" is not testing one.
# The criterion that would decide the result first, then the estimand, then
# the protocol's own hypothesis, and the narrative claim last. A narrative
# paragraph is the weakest statement of what a study commits to.
# The fields a protocol *commits* in, in the order their authority runs: the
# criterion that would decide the result, then the estimand, then the
# protocol's own hypothesis. `causal_claim` is not among them. It is the
# narrative paragraph, and letting it decide a mismatch the criterion did not
# state is exactly what hard-blocked three faithful protocols whose criteria
# used wording the reader did not know (C04, C17, C25). It is still read, for
# whether the claim is causal and for whether the protocol contradicts itself.
_CLAIM_FIELDS = ("support_if", "primary_estimand", "hypothesis")
_NARRATIVE_FIELD = "causal_claim"
# The estimand names a contrast, so the bare word "difference" in it is not
# a two-sided claim. Only a signed statement there commits to a direction.
_SIGNED_ONLY = (False, True, False)

# How much a relation commits to. A directional claim says more than a
# two-sided one, and a two-sided one says more than nothing.
_STRENGTH = {sc.UNSPECIFIED: 0, sc.EQUIVALENCE: 1, sc.TWO_SIDED: 1,
             sc.INCREASE: 2, sc.DECREASE: 2}


def _claim_fields(protocol) -> tuple[str, ...]:
    return tuple(str(getattr(protocol, name, "") or "") for name in _CLAIM_FIELDS)


def _all_claim_text(protocol) -> tuple[str, ...]:
    """Every field that says anything about the claim, narrative included."""
    return _claim_fields(protocol) + (
        str(getattr(protocol, _NARRATIVE_FIELD, "") or ""),)


def _describe(form: str) -> str:
    return sc.Relation(form=form).describe()


def _claim_scope(intent: StructuredIntent, protocol, approved_primary, primary_id,
                 domain: str = "") -> list:
    """
    Whether the protocol's claim says the same amount, about the same outcome,
    as the approved intent does.

    Five relations, not two. Forcing an association or a two-sided difference
    into increase-or-decrease is how a directional hypothesis tested
    two-sidedly passed, and how a non-inferiority clause about one outcome
    redefined the direction of another.
    """
    findings: list[Finding] = []
    outcome = primary_id or (approved_primary[0] if approved_primary else "")
    if not outcome:
        return findings

    approved_relation = intent.relation
    if not approved_relation.stated and intent.direction:
        approved_relation = sc.Relation(form=intent.direction)
    if not approved_relation.stated:
        return findings

    protocol_relation = sc.relation_from_fields(_claim_fields(protocol), outcome,
                                                domain, _SIGNED_ONLY)
    protocol_relation = sc.Relation(
        form=protocol_relation.form,
        causal=_protocol_causality(protocol),
        anchored=protocol_relation.anchored,
        evidence=protocol_relation.evidence)
    if not protocol_relation.stated:
        # The approval commits to a relation and the protocol's own fields do
        # not resolve to one. That is not a mismatch and not agreement.
        findings.append(Finding(
            AMBIGUOUS_MAPPING,
            f"the approved intent says the effect {_describe(approved_relation.form)}, and "
            f"no claim field of the protocol states a relation for {sc.label(outcome)} "
            "that could be compared with it"
            + (f" ({protocol_relation.evidence})" if protocol_relation.evidence else ""),
            approved_relation.form, protocol_relation.form))
        return findings

    approved_form, protocol_form = approved_relation.form, protocol_relation.form
    if approved_form != protocol_form:
        directional = (sc.INCREASE, sc.DECREASE)
        if approved_form in directional and protocol_form in directional:
            findings.append(Finding(
                CLAIM_DIRECTION_REVERSED,
                f"the approved intent says the effect {_describe(approved_form)}; the "
                f"protocol claims it {_describe(protocol_form)}",
                approved_form, protocol_form))
        elif _STRENGTH[protocol_form] < _STRENGTH[approved_form]:
            findings.append(Finding(
                CLAIM_SCOPE_WEAKENED,
                f"the approved intent says the effect {_describe(approved_form)}; the "
                f"protocol only claims it {_describe(protocol_form)}, which the stated "
                "outcome could not distinguish from the opposite effect",
                approved_form, protocol_form))
        else:
            findings.append(Finding(
                CLAIM_SCOPE_EXPANDED,
                f"the approved intent says the effect {_describe(approved_form)}; the "
                f"protocol claims it {_describe(protocol_form)}, which is a stronger "
                "claim than was approved", approved_form, protocol_form))

    # Causation where only an association was approved, and the reverse.
    if approved_relation.causal == sc.ASSOCIATIONAL and protocol_relation.causal == sc.CAUSAL:
        findings.append(Finding(
            CLAIM_SCOPE_EXPANDED,
            "the approved intent is about association and the protocol claims causation",
            "association", "causation"))
    elif approved_relation.causal == sc.CAUSAL and \
            protocol_relation.causal == sc.ASSOCIATIONAL:
        findings.append(Finding(
            CLAIM_SCOPE_WEAKENED,
            "the approved intent claims causation and the protocol reports an association",
            "causation", "association"))
    return findings


def _generality(intent: StructuredIntent, protocol) -> list:
    """
    Whether the protocol claims its result holds beyond what it studied.

    Prose, so never a contradiction and never blocking. It exists because a
    protocol offering one two-arm comparison as establishing a mechanism
    "across overseer models, pools and deployment settings" passed every check
    there was (C05). A person decides whether the study licenses that; the gate
    only refuses to let it through unread.
    """
    approved_text = f"{intent.research_question} {intent.hypothesis}"
    if sc.generalisation_markers(approved_text):
        return []                        # the approval claims the same ground
    claimed: list[str] = []
    for name in ("causal_claim", "hypothesis", "support_if"):
        claimed += sc.generalisation_markers(str(getattr(protocol, name, "") or ""))
    if not claimed:
        return []
    return [Finding(
        CLAIM_SCOPE_GENERALISED,
        "the protocol claims its result holds beyond what it studied "
        f"({', '.join(sorted(set(claimed)))}), and no approved source claims that ground",
        "the studied comparison", ", ".join(sorted(set(claimed))))]


def _protocol_causality(protocol) -> str:
    """
    Whether the protocol asserts a cause or an association, by field precedence.

    Not by scanning everything at once. A protocol carries the approved
    hypothesis in a field of its own, so a concatenation of all its claim text
    contains whatever the approval said -- and an approval that said
    "associated with" made a protocol asserting "causes" read as
    associational, which hid a claim that had been strengthened
    (OD-5, benchmark_v2). The narrative claim is where a protocol says what it
    is claiming, so it is asked first.
    """
    for name in (_NARRATIVE_FIELD, "primary_estimand", "support_if", "hypothesis"):
        stated = sc.causality(str(getattr(protocol, name, "") or ""))
        if stated != sc.UNSTATED:
            return stated
    return sc.UNSTATED


def _internal_consistency(protocol, outcome: str, domain: str) -> list:
    """
    Whether the protocol agrees with itself about what it is testing.

    A protocol whose support criterion tests a direction and whose causal
    claim asserts the opposite one, or whose narrative asserts causation
    while its estimand reports an association, has not been checked against
    the approval at all yet -- it disagrees with itself, and no reading of it
    can be the right one. Only genuine incompatibility counts: prose that
    commits to less than the criterion is normal writing, not a defect.
    """
    findings: list[Finding] = []
    if not outcome:
        return findings
    reads = {}
    for name in _CLAIM_FIELDS + (_NARRATIVE_FIELD,):
        text = str(getattr(protocol, name, "") or "")
        if not text:
            continue
        relation = sc.relation_for(text, outcome, domain)
        if relation.stated:
            reads[name] = relation

    directional = {name: r for name, r in reads.items()
                   if r.form in (sc.INCREASE, sc.DECREASE)}
    forms = {r.form for r in directional.values()}
    if len(forms) > 1:
        where = ", ".join(f"{n} says it {sc.Relation(form=r.form).describe()}"
                          for n, r in sorted(directional.items()))
        findings.append(Finding(
            CLAIM_INTERNALLY_INCONSISTENT,
            f"the protocol contradicts itself about {sc.label(outcome)}: {where}",
            "one direction", where))

    causal = {sc.causality(str(getattr(protocol, name, "") or ""))
              for name in (_NARRATIVE_FIELD, "primary_estimand")
              if getattr(protocol, name, "")}
    if sc.CAUSAL in causal and sc.ASSOCIATIONAL in causal:
        findings.append(Finding(
            CLAIM_INTERNALLY_INCONSISTENT,
            "the protocol asserts a cause in one field and an association in "
            "another, so what it claims to establish is not settled",
            "one kind of claim", "both"))
    return findings

def _criteria(intent: StructuredIntent, protocol, approved_primary,
              wanted_secondary, domain: str = "") -> list:
    """
    What the protocol would have to show, against what was approved.

    A support condition is the study's decision rule. Adding a clause to it
    changes what counts as a result, and a protocol that could reject the
    approved hypothesis on a ground nobody approved is not running the
    approved study -- but it has not contradicted anything either, so it is a
    question rather than a failure.
    """
    findings: list[Finding] = []
    approved_outcomes = set(approved_primary) | set(wanted_secondary)
    if not approved_outcomes:
        return findings

    support = str(getattr(protocol, "support_if", "") or "")
    for clause in sc.clauses(support):
        outcome = sc.resolve(clause, sc.OUTCOME, domain)
        if not outcome or outcome in approved_outcomes:
            continue
        if sc.relation_for(clause, outcome, domain).form == sc.UNSPECIFIED:
            continue
        findings.append(Finding(
            SUCCESS_CRITERION_ADDED,
            f"the protocol requires {sc.label(outcome)} to behave a certain way before "
            "the hypothesis counts as supported, and no approved source asks for that: "
            f"{clause.strip()}",
            ", ".join(sc.label(c) for c in sorted(approved_outcomes)), clause.strip()))

    # A preserved outcome may not be allowed to fall.
    for concept_id in intent.concepts("preserved_outcomes"):
        relation = sc.relation_from_fields(_claim_fields(protocol), concept_id,
                                           domain, _SIGNED_ONLY)
        if relation.form == sc.DECREASE:
            findings.append(Finding(
                PRESERVED_OUTCOME_VIOLATED,
                f"the approved intent requires {sc.label(concept_id)} not to fall, and "
                "the protocol's claim is that it does",
                f"{sc.label(concept_id)} not reduced", relation.evidence))

    # A second outcome given equal billing in the estimand is a second primary.
    estimand = str(getattr(protocol, "primary_estimand", "") or "")
    named = {sc.resolve(clause, sc.OUTCOME, domain) for clause in sc.clauses(estimand)}
    for outcome in sorted(o for o in named if o and o not in approved_outcomes):
        findings.append(Finding(
            OUTCOME_ADDED if intent.enumerated("primary_outcome") else UNAPPROVED_ADDITION,
            f"the protocol's primary comparison also estimates {sc.label(outcome)}, "
            "which no approved source names as an outcome",
            ", ".join(sc.label(c) for c in sorted(approved_outcomes)), estimand))
    return findings


def _unit(intent: StructuredIntent, protocol, seen: dict, domain: str = "") -> list:
    """
    The level the protocol analyses, read from the head of its own phrase.

    Never by asking whether a word appears: "task, aggregated over the trials
    of a task" is task-level and says "trials", and matching the word is how a
    study that moved up a level passed the check that existed to catch it.
    """
    findings: list[Finding] = []
    stated = intent.concepts("unit") or ((intent.unit,) if intent.unit else ())
    if not stated:
        return findings
    approved_unit = sc.resolve(stated[0], sc.UNIT, domain)

    stated_unit = str(getattr(protocol, "unit_of_analysis", "") or "")
    no_unit = "nothing"
    protocol_unit, note = sc.read_unit(stated_unit)
    seen["unit"] = {"approved": [approved_unit or stated[0]],
                    "approved_resolved": bool(approved_unit),
                    "protocol": protocol_unit or None, "note": note}
    if not approved_unit or not protocol_unit:
        # One side has no canonical unit, so there is nothing to contradict.
        # Comparing a resolved unit against an unresolved literal is how a
        # protocol analysing each "participant_learner" was called a changed
        # unit against an approval that said "student" (X19, 20260922).
        findings.append(Finding(
            IDENTITY_UNRESOLVED,
            f"the approved intent analyses each {stated[0]} and the protocol analyses "
            f"{stated_unit or no_unit}; at least one of those has no canonical unit, so "
            "whether they are the same level cannot be decided here"
            + (f" ({note})" if note else ""),
            stated[0], stated_unit))
    elif protocol_unit != approved_unit:
        findings.append(Finding(
            UNIT_OF_ANALYSIS_CHANGED,
            f"the approved intent analyses each {approved_unit}; the protocol analyses "
            f"{protocol.unit_of_analysis}", approved_unit, protocol.unit_of_analysis))
    return findings

def _invented_downstream(intent: StructuredIntent, protocol) -> list:
    """
    Scientific choices the protocol made that no approved source defines.

    This is the rule that keeps the precedence honest in the direction that
    costs something. Letting the hypothesis supply what the question omitted
    removes false blocks; without this, the same leniency would let the
    *protocol* supply what both of them omitted, and a comparator invented by
    a builder would read as approved science. It never blocks on its own --
    nothing was contradicted -- and it never passes either.
    """
    findings: list[Finding] = []
    unspecified = set(intent.unspecified)

    if "comparator" in unspecified:
        findings.append(Finding(
            INTENT_UNSPECIFIED,
            "no approved source names what the comparison is against; the protocol "
            f"compares against {', '.join(protocol.conditions) or 'nothing'}",
            "unspecified", ", ".join(protocol.conditions)))
    if "primary_outcome" in unspecified:
        findings.append(Finding(
            INTENT_UNSPECIFIED,
            "no approved source names the outcome; the protocol measures "
            f"{protocol.primary_metric or 'nothing'}", "unspecified",
            protocol.primary_metric))
    if "intervention" in unspecified:
        findings.append(Finding(
            INTENT_UNSPECIFIED,
            "no approved source names what is intervened on; the protocol varies "
            f"{', '.join(protocol.independent_variables) or 'nothing'}",
            "unspecified", ", ".join(protocol.independent_variables)))
    if "direction" in unspecified:
        findings.append(Finding(
            INTENT_UNSPECIFIED,
            "no approved source states a relation between the intervention and the "
            "outcome; the protocol would count the hypothesis supported if "
            f"{protocol.support_if or 'nothing stated'}",
            "unspecified", protocol.support_if))
    return findings


_REVIEWER_SYSTEM = (
    "You are checking whether a study protocol still expresses the research question it "
    "came from. You are not judging whether the study is good. Answer in JSON: "
    "{\"mismatches\": [\"...\"]}. List a mismatch only if you can name the specific thing "
    "the question asked for that the protocol does not do. An empty list is the right "
    "answer when the protocol matches."
)


def _ask_a_reviewer(intent: StructuredIntent, protocol, reviewer) -> tuple[str, list]:
    """One model call, and only doubts are taken from it. It cannot clear a mismatch."""
    from router import TaskType

    prompt = (f"Approved research question:\n{intent.research_question}\n\n"
              f"Approved hypothesis:\n{intent.hypothesis}\n\n"
              f"Protocol built from it:\n{protocol.to_json()}\n\n"
              "What did the question ask for that this protocol does not do?")
    try:
        raw = reviewer.generate(prompt=prompt, system=_REVIEWER_SYSTEM,
                                task_type=TaskType.QUALITY_REVIEW, max_tokens=800,
                                temperature=0.0)
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        mismatches = [str(m) for m in (data.get("mismatches") or []) if str(m).strip()]
    except Exception as exc:
        logger.warning("The fidelity reviewer could not be used: %s", exc)
        return "", []
    return raw[:500], [Finding(AMBIGUOUS_MAPPING, f"reviewer: {m}") for m in mismatches[:5]]


# --- the human-visible boundary -------------------------------------------------------

def scientific_summary(protocol, fidelity: Fidelity, review=None) -> str:
    """
    The study in plain terms, written before it is frozen.

    This is the oversight boundary: if a person reads one thing before a study
    is built, it is this, and it has to be readable without opening any code.
    """
    def listed(values) -> str:
        return ", ".join(values) if values else "-"

    methodology = review.verdict if review is not None else "not run"
    return f"""# Scientific summary - before freeze

**Research question**
{protocol.research_question or "-"}

**Hypothesis**
{protocol.hypothesis or "-"}

| | |
|---|---|
| Study type | {protocol.study_type.value} |
| Intervention | {listed(protocol.independent_variables)} |
| Conditions | {listed(protocol.conditions)} |
| Primary outcome | {protocol.primary_metric or "-"} |
| Secondary outcomes | {listed(protocol.secondary_metrics)} |
| Held constant | {listed(protocol.held_constant)} |
| Primary comparison | {protocol.primary_estimand or "-"} |
| Unit of analysis | {protocol.unit_of_analysis or "-"} |
| Ground truth | {protocol.ground_truth or "-"} |
| Supports the hypothesis if | {protocol.support_if or "-"} |
| Counts against it if | {protocol.reject_if or "-"} |

**Intent fidelity: {fidelity.status}** - {fidelity.summary()}
{_provenance_block(fidelity)}
**Methodology review: {methodology}**

{_findings_block(fidelity)}

Protocol version {protocol.protocol_version}, hash `{protocol.protocol_hash}`,
status {protocol.status.value}.
"""


def _provenance_block(fidelity: Fidelity) -> str:
    """Which approved source each compared term came from, and what none did."""
    if not fidelity.sources and not fidelity.unspecified:
        return ""
    nl = chr(10)
    ranked = ", ".join(f"{slot} from the {source.replace(chr(95), chr(32))}"
                       for slot, source in sorted(fidelity.sources.items()))
    missing = ", ".join(fidelity.unspecified) or "none"
    reconstructed = sorted(
        slot for slot, detail in (fidelity.concepts or {}).items()
        if isinstance(detail.get("protocol"), dict)
        and any(entry.get("identity") == sc.FROM_REGISTRY
                for entry in detail["protocol"].values()))
    lines = [nl + "_Read from:_ " + (ranked or "nothing") + "  ",
             "_Defined by no approved source:_ " + missing]
    if reconstructed:
        lines.append("_Identity reconstructed from wording, not carried:_ "
                     + ", ".join(reconstructed))
    return nl.join(lines)


def _findings_block(fidelity: Fidelity) -> str:
    if not fidelity.findings:
        return "_No fidelity findings._"
    rows = ["| Code | What the approved intent asked | What the protocol says |",
            "|---|---|---|"]
    for finding in fidelity.findings:
        rows.append(f"| `{finding.code}` | {finding.approved_intent or finding.detail} | "
                    f"{finding.protocol_says or '-'} |")
    return chr(10).join(rows)


def write_summary(protocol, fidelity: Fidelity, folder: Path | str, review=None) -> Path:
    """Persist the summary beside the study, so the boundary leaves a trace."""
    path = Path(folder) / SUMMARY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scientific_summary(protocol, fidelity, review), encoding="utf-8")
    return path


# --- carrying identity into the protocol ----------------------------------------------

_PROTOCOL_KINDS = (("independent_variables", sc.INTERVENTION), ("conditions", sc.CONDITION),
                   ("primary_metric", sc.OUTCOME), ("secondary_metrics", sc.OUTCOME),
                   ("held_constant", sc.CONSTANT))


def _values_with_kind(protocol):
    for name, kind in _PROTOCOL_KINDS:
        value = getattr(protocol, name, None)
        for item in ((value,) if isinstance(value, str) else (value or ())):
            if str(item).strip():
                yield str(item), kind


def propagate_identity(protocol, approved: ApprovedIntent | None = None):
    """
    Attach a concept id to every display name the protocol uses.

    Two sources, in that order. An id the approval carried is matched to the
    protocol's wording **by that wording**, never by slot position: stamping
    the approved outcome's id onto whatever happens to sit in `primary_metric`
    would make a substituted outcome look approved, which is the failure this
    whole gate exists for. Everything the approval did not carry is resolved
    from the registry and recorded as reconstructed, so a later reader can
    tell the two apart.

    Returns a new protocol. It is called before the freeze so the identities
    are part of what is frozen, and it never changes anything else.
    """
    import dataclasses

    carried = dict(getattr(protocol, "concepts", None) or {})
    provenance = dict(getattr(protocol, "concept_provenance", None) or {})
    written = {value for value, _ in _values_with_kind(protocol)}
    domain = (approved.domain if approved else "") or sc.domain_of(protocol)

    for key, value in ((approved.structured if approved else None) or {}).items():
        if not _STRUCTURED_ALIASES.get(str(key).strip().lower()):
            continue
        for item in (value if isinstance(value, (list, tuple)) else (value,)):
            if not isinstance(item, dict):
                continue
            concept_id = str(item.get("concept_id") or "").strip()
            if not concept_id:
                continue
            for name in (item.get("display_name"), item.get("name"), concept_id):
                name = str(name or "").strip()
                if name and name in written and name not in carried:
                    carried[name] = concept_id
                    provenance[name] = sc.FROM_APPROVED

    for value, kind in _values_with_kind(protocol):
        if value in carried:
            continue
        concept_id = sc.resolve(value, kind, domain)
        if concept_id:
            carried[value] = concept_id
            provenance[value] = sc.FROM_REGISTRY

    if carried == (getattr(protocol, "concepts", None) or {}):
        return protocol
    return dataclasses.replace(protocol, concepts=carried, concept_provenance=provenance)
