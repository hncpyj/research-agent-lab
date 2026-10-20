"""
Canonical identities for the things a study is about.

The unseen pilot of 2026-09-22 blocked three faithful protocols because the
fidelity gate compared *wording*. An approved intent that said
`curation_condition` and a protocol that said `curation_strategy` were called a
changed intervention; `target_selection_rate` against
`share_of_trials_selecting_target` was called a changed outcome. Both are one
thing written twice, and every fix that stays at the level of words is a longer
list of words.

So identity moves up a level. A concept id names the scientific thing, wording
names it for a person, and the two travel together:

    concept_id      target_selection          what it is
    display_name    share of trials selecting the target   what it is called

The id is what the gate compares. The registry below is the shared vocabulary
the ids are drawn from, and resolving a display name to an id is the *fallback*
for when nothing upstream propagated one -- not the primary path. Where neither
a propagated id nor a registry match is available, the gate says so and a
person decides; it does not guess from prefixes.

This is not a second source of scientific truth. It assigns names to the
science that the approved intent and the frozen protocol already state; it
never decides what a study is about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- kinds of thing a concept can be --------------------------------------------------
#
# A concept's kind is part of its identity. A token that identifies an outcome
# must never identify a condition, and the resolver is never asked to answer
# without one.

OUTCOME = "outcome"
INTERVENTION = "intervention"
CONDITION = "condition"
CONSTANT = "constant"
UNIT = "unit"

# The names the protocol vocabulary uses for two of these. An outcome is the
# thing measured and the metric is how it is measured, and this system does not
# separate them; a held-constant is this system's control. Both spellings are
# accepted so a caller can say what it means.
METRIC = OUTCOME
CONTROL = CONSTANT
UNIT_OF_ANALYSIS = UNIT

KINDS = (OUTCOME, INTERVENTION, CONDITION, CONSTANT, UNIT)


# --- domains ---------------------------------------------------------------------------
#
# The defect this scoping closes, recorded here because the rule only makes
# sense with it. A memory outcome called `delayed_recall_score` was resolved to
# `classification_accuracy`, because that concept accepts the stem `recall` as
# in precision-and-recall. The approved side carried its correct identity, the
# protocol side was handed a confident wrong one, and the gate saw two known
# identities that differed and called it a contradiction. A faithful protocol
# was blocked by a coincidence of English.
#
# So a concept belongs to a domain, and a term is resolved only against the
# domain it is being read in. Three rules, each with its reason:
#
#   1. A concept resolves only within its own domain. `recall` in a classifier
#      and `recall` in a memory task are different concepts that share a word,
#      and nothing about the word says which is meant.
#   2. A concept marked UNIVERSAL resolves in any domain. Only things that
#      genuinely do not vary by field are marked so -- the unit of analysis is
#      a trial or a patient or a coupon whatever the study is about.
#   3. When the domain is not known, only UNIVERSAL concepts may resolve.
#      Everything else abstains. An unknown domain is exactly the case where a
#      shared word is most likely to mislead.
#
# The rule is abstention, not coverage. Adding every term seen in an evaluation
# would make that evaluation pass and say nothing about the next one.

CHOICE_SET = "choice_set"        # curation of an overseer's options
ML_EVAL = "ml_eval"              # training and evaluating models
UNIVERSAL = "universal"          # genuinely field-independent

DOMAINS = (CHOICE_SET, ML_EVAL, UNIVERSAL)

# Which domain a study belongs to, by the scaffold that implements it. A
# scaffold this system does not know is an unknown domain, not a default one.
_DOMAIN_BY_SCAFFOLD = {
    "controlled_llm": CHOICE_SET,
    "nlp_training": ML_EVAL,
    "cv_training": ML_EVAL,
    "rl_training": ML_EVAL,
    "retrieval": ML_EVAL,
    "domain_adaptation": ML_EVAL,
}


def domain_of(protocol_or_scaffold) -> str:
    """
    The domain a protocol's terms should be read in, or "" when it is unknown.

    Returning "" is a real answer: it means only field-independent concepts may
    resolve, and everything else is unresolved and goes to a person.
    """
    scaffold = getattr(protocol_or_scaffold, "scaffold_id", protocol_or_scaffold)
    return _DOMAIN_BY_SCAFFOLD.get(str(scaffold or "").strip().lower(), "")


# Where an identity came from. Recorded for every concept the gate uses, so a
# verdict can be traced to whether identity was carried or reconstructed.
FROM_APPROVED = "approved_intent"     # propagated from what a person signed off
FROM_REGISTRY = "registry"            # reconstructed from wording (the fallback)
UNRESOLVED = "unresolved"             # no identity available; not a guess


# --- how much evidence is enough to claim a concept ------------------------------------
#
# The defect this rule closes. `candidate_pool` accepted any pool-ish word, so
# `pool_generation_procedure` -- a procedure for making pools, not the pool --
# was read as the approved constant being held fixed, and a study giving each
# arm its own freshly generated pool passed (C18, 2026-09-22). The same shape
# gave `baseline_condition` the identity of `control_condition` (C07) and
# `decision_episode` the identity of the universal `episode` (C09).
#
# The words below carry no identity on their own. They are the nouns every
# study in every field uses for its furniture, and sharing one with a concept
# is not evidence of being that concept.
GENERIC_STEMS = frozenset({
    "pool", "condition", "score", "rate", "trial", "episod", "select", "metric",
    "option", "set", "model", "value", "count", "procedur", "polic", "level",
    "stage", "share", "proportion", "fraction", "measur", "outcom", "variabl",
    "group", "arm", "run", "session", "item", "block", "task", "unit", "test",
    "control", "baselin", "standard", "regime", "policy", "configur", "setting",
})


def _distinctive(stem: str) -> bool:
    return stem not in GENERIC_STEMS


def _canonical(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


@dataclass(frozen=True)
class Concept:
    """
    One scientific thing, the domain it belongs to, and the stems that identify
    it in prose.

    `requires` is a tuple of groups. Every group must be satisfied by some word
    in the text, and a group is satisfied by any one of its stems. Groups are
    how a concept stays specific without being a phrase: target selection needs
    a target word *and* a choosing word, in any order and any wording.
    """
    concept_id: str
    kind: str
    domain: str
    label: str
    requires: tuple[frozenset[str], ...]
    # Phrases that name this concept outright. An exact match on one of these
    # is sufficient evidence by itself; nothing else is.
    canonical: tuple[str, ...] = ()

    def visible_in(self, domain: str) -> bool:
        """Whether this concept may be resolved while reading `domain`."""
        if self.domain == UNIVERSAL:
            return True
        return bool(domain) and self.domain == domain

    def canonical_forms(self) -> tuple[str, ...]:
        return tuple({_canonical(f) for f in (self.concept_id,) + self.canonical})

    def matches(self, lemmas: set[str], text: str = "") -> int:
        """
        How strongly this text evidences this concept, or 0 for not at all.

        Every group must still be satisfied. What is new is that satisfying
        them is not automatically enough: a claim needs either the concept's
        own name, or two independent parts of it, or one part that is not a
        word every study uses. One generic token is never enough.
        """
        if text and _canonical(text) in self.canonical_forms():
            return 100                                  # it says what it is
        total = 0
        distinctive_groups = 0
        for group in self.requires:
            hit_stems = [stem for stem in group
                         for word in lemmas if word.startswith(stem)]
            if not hit_stems:
                return 0
            total += len(hit_stems)
            if any(_distinctive(stem) for stem in hit_stems):
                distinctive_groups += 1
        if self.kind == UNIT:
            # A unit is named by furniture words by nature -- trial, task,
            # session. Its evidence is structural instead: `read_unit` requires
            # the unit word to stand alone at the head of the phrase, which is
            # a stronger test than any token could be.
            return total + len(self.requires)
        if len(self.requires) < 2 and distinctive_groups == 0:
            return 0            # one group, and only generic words in it
        if len(self.requires) >= 2 and distinctive_groups == 0:
            return 0            # several groups, all of them generic words
        return total + len(self.requires)      # more groups means more specific


def _c(concept_id, kind, domain, label, *groups, canonical=()) -> Concept:
    return Concept(concept_id, kind, domain, label,
                   tuple(frozenset(g) for g in groups), tuple(canonical))


REGISTRY: tuple[Concept, ...] = (
    # === the choice-set domain: curation of an overseer's options ============
    # -- outcomes ---------------------------------------------------------
    _c("target_selection", OUTCOME, CHOICE_SET, "selection of the target option",
       {"target", "designat"}, {"select", "pick", "choos", "chose", "choic"}),
    _c("explicit_approval", OUTCOME, CHOICE_SET, "explicit approval by the overseer",
       {"approv"}),
    _c("reject_all", OUTCOME, CHOICE_SET, "rejecting every option", {"reject"}),
    # Both halves are required. A concept that fires on the bare word "more"
    # would claim every clause saying an outcome rose "more often".
    _c("request_more_options", OUTCOME, CHOICE_SET, "asking for more options",
       {"request", "ask", "seek", "solicit"}, {"more", "additional", "further"}),
    _c("option_quality", OUTCOME, CHOICE_SET, "quality of the selected option",
       {"qualit"}),
    _c("decision_cost", OUTCOME, CHOICE_SET, "cost or latency of the decision",
       {"latenc", "token", "cost"}),

    # -- interventions ----------------------------------------------------
    _c("curation_condition", INTERVENTION, CHOICE_SET,
       "how the shown options are curated", {"curat"}),
    _c("prompt_ordering", INTERVENTION, CHOICE_SET,
       "the order options are presented in", {"order", "position", "sequenc"}),
    _c("overseer_identity", INTERVENTION, CHOICE_SET, "which overseer decides",
       {"overseer", "judge"}, {"model", "identit", "backend", "architect"}),
    _c("overseer_warning", INTERVENTION, CHOICE_SET,
       "whether the overseer is warned", {"warn", "caution", "disclos"}),

    # -- conditions -------------------------------------------------------
    _c("benign_curation", CONDITION, CHOICE_SET, "benign curation", {"benign"}),
    _c("adversarial_curation", CONDITION, CHOICE_SET, "adversarial curation",
       {"adversar"}),
    _c("neutral_curation", CONDITION, CHOICE_SET, "neutral curation", {"neutral"}),
    _c("random_curation", CONDITION, CHOICE_SET, "random curation", {"random"}),
    # "control" and "baseline" are design words, not this study's arms, so
    # this concept can only be claimed by its own name (C07).
    _c("control_condition", CONDITION, CHOICE_SET, "a control or baseline arm",
       {"control", "baselin"}, canonical=("control_condition",)),
    _c("full_pool_presentation", CONDITION, CHOICE_SET, "showing the whole pool",
       {"full", "unfilter", "whole", "entire", "complete"},
       {"pool", "present", "unfilter", "catalog"}),

    # -- things held constant ---------------------------------------------
    # Two parts on purpose. "pool" alone is furniture; a study that mentions a
    # pool-generation procedure has not said the pool is held fixed (C18).
    _c("candidate_pool", CONSTANT, CHOICE_SET, "the pool candidates are drawn from",
       {"candidat", "catalog", "inventor", "stock", "librar", "corpus"},
       {"pool", "set", "collection", "list"},
       canonical=("candidate_pool", "underlying_candidate_pool", "frozen_candidate_pool")),
    _c("overseer_configuration", CONSTANT, CHOICE_SET, "the overseer's configuration",
       {"overseer"}, {"config", "setup", "setting"}),
    _c("overseer_prompt", CONSTANT, CHOICE_SET, "the overseer's prompt",
       {"overseer"}, {"prompt"}),
    _c("trial_structure", CONSTANT, CHOICE_SET, "the structure of a trial",
       {"trial"}, {"structur", "design", "protocol"}),
    _c("shown_per_trial", CONSTANT, CHOICE_SET, "how many options are shown",
       {"shown", "number", "count", "size"}, {"trial", "option", "shown"}),
    _c("target_identity_distribution", CONSTANT, CHOICE_SET,
       "how the target is assigned", {"target"}, {"identit", "distribut", "assign"}),

    # === machine-learning training and evaluation ============================
    # `classification_accuracy` is the concept that caused the defect this
    # scoping exists for. It keeps its stems, and it is now invisible outside
    # its own domain, so a memory study's "delayed recall" cannot reach it.
    _c("classification_accuracy", OUTCOME, ML_EVAL, "accuracy of a classifier",
       {"accurac", "f1", "precision", "recall"}),
    _c("episode_return", OUTCOME, ML_EVAL,
       "return of a reinforcement-learning episode", {"episod", "return", "reward"}),
    _c("policy_architecture", INTERVENTION, ML_EVAL,
       "the learned policy's architecture", {"polic"}, {"architect", "network"}),
    _c("reward_function", CONSTANT, ML_EVAL, "the reward function", {"reward"}),
    _c("environment", CONSTANT, ML_EVAL, "the environment", {"environ"}),

    # === field-independent ===================================================
    # A unit of analysis is the same idea in every field: the thing one row of
    # the data is about. These are the only concepts allowed to resolve when
    # the domain is unknown.
    _c("trial", UNIT, UNIVERSAL, "one trial", {"trial"}),
    _c("task", UNIT, UNIVERSAL, "one task", {"task"}),
    _c("participant", UNIT, UNIVERSAL, "one participant", {"participant", "subject"}),
    _c("session", UNIT, UNIVERSAL, "one session",
       {"session", "conversation", "dialogue"}),
    _c("episode", UNIT, UNIVERSAL, "one episode", {"episod", "rollout"}),
    _c("item", UNIT, UNIVERSAL, "one item", {"item"}),
    _c("block", UNIT, UNIVERSAL, "one block", {"block"}),
)

_BY_ID = {concept.concept_id: concept for concept in REGISTRY}

_SPLIT = re.compile(r"[^a-z0-9]+")


def lemmas(text: str) -> set[str]:
    """The words of a phrase, lowercased, with a trailing plural removed."""
    words = set()
    for word in _SPLIT.split(str(text).lower()):
        if len(word) < 3:
            continue
        words.add(word)
        if word.endswith("s") and len(word) > 3:
            words.add(word[:-1])
    return words


def concept(concept_id: str) -> Concept | None:
    return _BY_ID.get(concept_id)


def label(concept_id: str) -> str:
    found = _BY_ID.get(concept_id)
    return found.label if found else concept_id


def resolve(text: str, kind: str, domain: str = "") -> str:
    """
    The concept a display name refers to, or "" when nothing safely fits.

    A kind is required: a token that identifies an outcome must not be allowed
    to identify a condition. A domain narrows it further, and an unknown
    domain admits only field-independent concepts.

    Returning "" is a real answer and the caller must handle it. An
    unrecognised name is not evidence of sameness and not evidence of
    difference. The most specific match wins, and a tie returns "" rather
    than picking one.
    """
    if not kind or not str(text).strip():
        return ""
    words = lemmas(text)
    scored: list[tuple[int, str]] = []
    for candidate in REGISTRY:
        if candidate.kind != kind or not candidate.visible_in(domain):
            continue
        score = candidate.matches(words, text)
        if score:
            scored.append((score, candidate.concept_id))
    if not scored:
        return ""
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return ""                         # ambiguous; the caller escalates
    return scored[0][1]

def resolve_all(values, kind: str, domain: str = "") -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    Resolve a list of display names. Returns (concept ids, names that did not
    resolve), keeping both because the unresolved ones are what a person has to
    look at.
    """
    found: list[str] = []
    missed: list[str] = []
    for value in values or ():
        concept_id = resolve(value, kind, domain)
        (found if concept_id else missed).append(concept_id or str(value))
    return tuple(dict.fromkeys(found)), tuple(missed)


# --- the unit of analysis -------------------------------------------------------------
#
# A protocol writes the unit as prose, and the prose often mentions the level
# *below* it: "task, aggregated over the trials of a task" is task-level and
# says "trials" twice. Matching the word anywhere is how a study that moved
# from trials to tasks passed a check that existed to catch exactly that.

_UNIT_TAIL = re.compile(r"[(,;:]|\baggregat\w*\b|\bnested\b|\baveraged\b|\bpooled\b"
                        r"|\bcollapsed\b|\bover\b|\bwithin\b|\bacross\b|\bper\b")


def read_unit(text: str) -> tuple[str, str]:
    """
    The unit a protocol analyses, read from the head of the phrase.

    Two rules, and the second is new. The head is taken first, because the
    prose often names the level below ("task, aggregated over the trials of a
    task" is task-level and says "trials" twice). And the head must *be* the
    unit rather than contain it: "decision_episode" is a compound of two
    content words, and claiming the universal `episode` from it is how a
    faithful rename of the approved trial became a changed unit (C09).

    Returns (concept id, note). An empty id with a note means the caller must
    escalate rather than choose.
    """
    text = str(text or "").strip()
    if not text:
        return "", "the protocol names no unit of analysis"

    head = _UNIT_TAIL.split(text, maxsplit=1)[0].strip()
    for segment, where in ((head, "head"), (text, "whole phrase")):
        if not segment:
            continue
        words = lemmas(segment)
        hits = {c.concept_id for c in REGISTRY
                if c.kind == UNIT and c.matches(words, segment)}
        if len(hits) > 1:
            return "", (f"the unit of analysis names more than one level "
                        f"({chr(44).join(sorted(hits))}): {text}")
        if len(hits) == 1 and where == "head":
            # Everything in the head that is not the unit word and not a
            # bare modifier is another content word, and a compound of two
            # content words does not name one of them.
            extra = {w for w in words if len(w) > 2} - _UNIT_MODIFIERS
            unit = hits.copy().pop()
            extra = {w for w in extra if not _names_unit(w, unit)}
            if extra:
                return "", (f"the unit of analysis is a compound, "
                            f"{text!r}, so which level it names is not settled")
            return unit, ""
        if len(hits) == 1:
            return hits.pop(), ""
    return "", f"no unit of analysis could be read from {text!r}"


# Words that qualify a unit without naming a different one.
_UNIT_MODIFIERS = frozenset({
    "one", "single", "each", "per", "level", "the", "individual", "every",
    "wise", "analysis", "observation", "record", "row", "datum", "data",
})


def _names_unit(word: str, unit: str) -> bool:
    concept = _BY_ID.get(unit)
    if not concept:
        return False
    return any(word.startswith(stem) for group in concept.requires for stem in group)

# --- what a claim asserts -------------------------------------------------------------
#
# Five relations, because forcing everything into increase-or-decrease is how a
# directional hypothesis tested two-sidedly went unnoticed, and how "without
# lowering approval" turned an increase in selection into a decrease.

INCREASE = "increase"
DECREASE = "decrease"
TWO_SIDED = "two_sided"           # a difference, direction unstated
EQUIVALENCE = "equivalence"       # unchanged, or not worse: a non-inferiority clause
UNSPECIFIED = "unspecified"

CAUSAL = "causal"
ASSOCIATIONAL = "associational"
UNSTATED = "unstated"

_FORMS = {INCREASE: "increases", DECREASE: "decreases", TWO_SIDED: "changes",
          EQUIVALENCE: "is unchanged", UNSPECIFIED: "states no relation"}


@dataclass(frozen=True)
class Relation:
    """What a text says about one outcome."""
    form: str = UNSPECIFIED
    causal: str = UNSTATED
    anchored: bool = False            # read from a clause that named the outcome
    evidence: str = ""

    @property
    def stated(self) -> bool:
        return self.form != UNSPECIFIED

    def describe(self) -> str:
        return _FORMS.get(self.form, self.form)

    def as_dict(self) -> dict:
        return {"form": self.form, "causal": self.causal, "anchored": self.anchored,
                "evidence": self.evidence[:160]}


# Order matters. A negated fall is a non-inferiority clause, not a fall, so the
# equivalence patterns are tried first; a signed word beats the bare word
# "difference", so direction is tried before the two-sided patterns.
#
# The vocabulary is wider than it was because the last holdout hard-blocked
# three faithful protocols whose support criterion said "is above it" or
# "holds up" -- expressions the reader did not know, so it fell through to a
# narrative sentence that said "any change" and reported a weakened claim
# against a protocol that was testing a direction (C04, C17, C25).
_EQUIVALENCE = (
    r"\b(?:without|not|no|never)\s+(?:\w+\s+){0,2}?"
    r"(?:reduc|lower|decreas|fall|fell|drop|declin|diminish|suppress|smaller|worse)\w*",
    r"\bat least as\s+\w+",
    r"\b(?:does|did|do)\s+not\s+(?:\w+\s+){0,2}?"
    r"(?:reduc|lower|decreas|fall|drop|declin|differ|chang)\w*",
    r"\b(?:unchanged|unaffected|intact|preserved|comparable|equivalent|steady|"
    r"stable|maintained|undiminished|non-?inferior)\b",
    r"\bholds?\s+steady\b", r"\bstays?\s+(?:where|the same)\b",
    r"\bno\s+(?:loss|fall|drop|reduction|decline)\b", r"\bholds?\s+up\b",
    r"\bis\s+no\s+(?:lower|worse|smaller)\b", r"\bnot\s+reliably\s+lower\b",
    r"\bat\s+or\s+above\b", r"\bno\s+worse\s+than\b", r"\bis\s+not\s+below\b",
    r"\bnot\s+(?:below|lower|reduced|diminished)\b",
)
_INCREASE = (
    r"\b(?:increas|rais|rise|rose|risen|higher|greater|larger|more|exceed|elevat|"
    r"boost|grow|grew|positive|improv|outperform|surpass|outstrip)\w*",
    r"\bis\s+above\b", r"\bsits?\s+above\b", r"\brises?\s+above\b",
    r"\bgreater\s+than\b", r"\bmore\s+often\b", r"\bdriv\w*\s+up\b",
    r"\bstrictly\s+(?:larger|greater|higher)\b", r"\bgoes?\s+up\b",
    r"\blifts?\b", r"\bupward\b",
)
_DECREASE = (
    r"\b(?:reduc|decreas|lower|fall|fell|fallen|drop|declin|degrad|worse|less|"
    r"smaller|diminish|suppress|negative|underperform|shrink|shrank|shorten)\w*",
    r"\bis\s+below\b", r"\bfalls?\s+below\b", r"\bsits?\s+below\b",
    r"\blower\s+than\b", r"\bless\s+than\b", r"\bdriv\w*\s+down\b",
    r"\bgoes?\s+down\b", r"\bdownward\b",
)
_TWO_SIDED = (
    r"\b(?:differ|different|difference|chang|affect|influenc|vary|varies|"
    r"shift|impact|move|moves|moved)\w*",
    r"\bin\s+either\s+direction\b", r"\beither\s+way\b", r"\bwhichever\s+way\b",
    r"\btwo-?sided\b",
)

_CAUSAL = (r"\b(?:cause|causes|caused|causal|causally|because|drives?|driving|produces?|"
           r"leads? to|results? in|makes?|steers?|degrades?|induces?|attributable)\b",)
_NOT_CAUSAL = (r"\bwithout\s+(?:asserting|claiming|implying)\b",
               r"\bnot\s+(?:a\s+)?causal\b", r"\bno\s+causal\b",
               r"\bdoes not (?:assert|claim|imply)\b",
               r"\bno\s+causal\s+attribution\b", r"\bwith\s+no\s+claim\s+that\b")
_ASSOCIATIONAL = (r"\b(?:associat|correlat|relationship|linked|predict|co-?occur|"
                  r"accompan|alongside)\w*",
                  r"\bgoes?\s+together\s+with\b", r"\bobserved\s+to\s+be\b")

# Prose that claims the result holds beyond what was studied. Not an identity
# claim and never deterministic, so it escalates rather than blocking.
_GENERALISATION = (
    r"\bas a class\b", r"\bin general\b", r"\bgenerally\b", r"\bbroadly\b",
    r"\bacross\s+(?:models|systems|settings|domains|deployments|pools|materials|"
    r"routes|fields|tasks|populations)\b",
    r"\bany\s+(?:language[- ]model|model|overseer|system)\b",
    r"\bgeneral\s+(?:mechanism|capacity|principle|account|steering)\b",
    r"\bnot only in\b", r"\bbeyond\s+the\s+(?:studied|tested|sampled)\b",
    r"\bhold[s]?\s+for\s+\w+\s+in general\b",
)

_CLAUSE = re.compile(r"\s*(?:,|;|:|\band\b|\bwhile\b|\bwhereas\b|\bwithout\b|\bbut\b|"
                     r"\balthough\b|\bthough\b|\bwith\b)\s+")


def clauses(text: str) -> list[str]:
    """
    A claim broken where its subject can change.

    The split keeps the connective's own word out of the piece that follows it
    except for `without`, which is put back, because "without reducing
    approval" only means anything with the negation attached.
    """
    text = str(text or "")
    pieces: list[str] = []
    cursor = 0
    for match in _CLAUSE.finditer(text):
        pieces.append(text[cursor:match.start()])
        cursor = match.start() if match.group().strip() == "without" else match.end()
        if match.group().strip() == "without":
            cursor = match.start()
            # start the next clause at the connective itself
            nxt = _CLAUSE.search(text, match.end())
            pieces.append(text[cursor:nxt.start()] if nxt else text[cursor:])
            cursor = nxt.start() if nxt else len(text)
    pieces.append(text[cursor:])
    return [p.strip() for p in pieces if p.strip()]


def _form_of(clause: str, signed_only: bool = False) -> str:
    lowered = clause.lower()
    families = [(_EQUIVALENCE, EQUIVALENCE), (_INCREASE, INCREASE),
                (_DECREASE, DECREASE)]
    if not signed_only:
        # An estimand names the quantity being estimated, and every estimand is
        # a difference between arms. Reading the word "difference" there as a
        # two-sided *claim* is how a protocol whose estimand said "difference in
        # the fraction choosing the target, adversarial minus benign" was
        # reported as having abandoned its direction (C25, C27).
        families.append((_TWO_SIDED, TWO_SIDED))
    for patterns, form in families:
        for pattern in patterns:
            if re.search(pattern, lowered):
                return form
    return UNSPECIFIED


def causality(text: str) -> str:
    """Whether a claim asserts a cause, an association, or does not say."""
    lowered = str(text or "").lower()
    for pattern in _NOT_CAUSAL:
        if re.search(pattern, lowered):
            return ASSOCIATIONAL
    for pattern in _ASSOCIATIONAL:
        if re.search(pattern, lowered):
            return ASSOCIATIONAL
    for pattern in _CAUSAL:
        if re.search(pattern, lowered):
            return CAUSAL
    return UNSTATED


def relation_for(text: str, outcome_id: str, domain: str = "",
                 signed_only: bool = False) -> Relation:
    """
    What a text says about one named outcome, and nothing about any other.

    Only clauses that name the outcome are read. This is the whole point: a
    hypothesis that increases selection *without reducing approval* says
    "increase" about selection and "not reduced" about approval, and reading
    the first direction word in the sentence gets both wrong.
    """
    text = str(text or "")
    if not text.strip() or not outcome_id:
        return Relation()

    found: list[tuple[str, str]] = []
    for clause in clauses(text):
        if resolve(clause, OUTCOME, domain) != outcome_id:
            continue
        form = _form_of(clause, signed_only)
        if form != UNSPECIFIED:
            found.append((form, clause))
    if not found:
        return Relation(causal=causality(text))

    forms = {form for form, _ in found}
    if len(forms) > 1:
        # The text says two different things about one outcome. That is not a
        # verdict the gate may pick a side of.
        return Relation(form=UNSPECIFIED, causal=causality(text), anchored=True,
                        evidence="the claim says " +
                                 " and ".join(sorted(forms)) + f" about {outcome_id}")
    form, clause = found[0]
    return Relation(form=form, causal=causality(text), anchored=True, evidence=clause)


def relation_from_fields(fields: tuple[str, ...], outcome_id: str,
                         domain: str = "",
                         signed_only: tuple[bool, ...] = ()) -> Relation:
    """
    The relation a protocol commits to, read from its fields in order.

    The order is deliberate: the criterion that would decide the result is
    read before the prose that describes it. A protocol whose support
    condition says "higher" is testing a direction whatever its narrative
    paragraph says, and one whose support condition says "differs" is not.

    And the reading stops at the first field that *names the outcome*, even
    if that field states no relation this reader knows. Falling through from
    an explicit criterion to a narrative sentence is how a protocol whose
    criterion said "is above it" was reported as claiming "any change"
    (C04, C17, C25). An unreadable criterion is an unreadable criterion, and
    the answer to that is a person, not the next paragraph.
    """
    whole = " ".join(f for f in fields if f)
    for index, field_text in enumerate(fields):
        if not field_text:
            continue
        only_signed = signed_only[index] if index < len(signed_only) else False
        relation = relation_for(field_text, outcome_id, domain, only_signed)
        if relation.stated:
            return Relation(form=relation.form, causal=causality(whole),
                            anchored=True, evidence=relation.evidence)
        if relation.anchored:
            # It talks about this outcome and says something this reader
            # cannot classify. Stop here rather than borrow a later sentence.
            return Relation(form=UNSPECIFIED, causal=causality(whole), anchored=True,
                            evidence=relation.evidence or field_text[:160])
    return Relation(form=UNSPECIFIED, causal=causality(whole), anchored=False,
                    evidence="")


def generalisation_markers(text: str) -> list[str]:
    """
    Phrases claiming the result holds beyond what was studied.

    Never a contradiction on its own -- prose is not a protocol field -- so a
    caller escalates on it rather than blocking. It exists because a protocol
    offering one two-arm comparison as establishing a mechanism "across
    overseer models, pools and deployment settings" passed everything (C05).
    """
    lowered = str(text or "").lower()
    return [m.group(0) for pattern in _GENERALISATION
            for m in re.finditer(pattern, lowered)]


def resolve_foreign(text: str, kind: str, domain: str) -> tuple[str, str]:
    """
    Whether a term belongs unambiguously to a *different* known field.

    The companion to abstention, and it only applies when the field being read
    in is known. `policy_architecture` in a choice-set study is not an
    unreadable name: it is a name that belongs to another field, and a protocol
    built from another field's vocabulary has changed field. Two identities
    that resolve, in two different domains, are two known identities that
    differ.

    When the reading domain is unknown this returns nothing at all. That is the
    case where a shared word is most likely to mislead, and it is where
    `delayed recall` was handed a classifier's `recall`; there is no safe
    inference to draw and the answer is to abstain.

    Returns (concept id, domain) or ("", "").
    """
    if not domain or not kind or not str(text).strip():
        return "", ""
    words = lemmas(text)
    found: list[tuple[int, str, str]] = []
    for candidate in REGISTRY:
        if candidate.kind != kind or candidate.domain in (domain, UNIVERSAL):
            continue
        score = candidate.matches(words, text)
        if score:
            found.append((score, candidate.concept_id, candidate.domain))
    if len(found) != 1:
        return "", ""                    # nothing, or more than one field: abstain
    _, concept_id, other = found[0]
    return concept_id, other
