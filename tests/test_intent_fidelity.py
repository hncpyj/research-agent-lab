"""
The gate that asks whether the protocol is still the study that was approved.

It is separate from the methodology review on purpose, and the separation is
what these tests mostly pin: a sound design for the wrong question must not
pass, and the right question badly designed must not pass either. Neither
verdict may override the other, and neither may be produced by rewriting the
protocol into agreement.

The cases below are the permanent regression set named in the workflow, and
the last group pins the precedence of approved sources over the question.
They are deterministic: no model is called, and every mutation is a mutation a
generator has actually been observed to make, or an obvious neighbour of one.
"""
import dataclasses
from pathlib import Path

import pytest

from agents import intent_fidelity as fid
from agents.experiment_agent import build_spec
from agents.study_protocol import OutputContract, StudyType

QUESTION = ("Holding the underlying candidate pool fixed, adversarial curation increases "
            "target-option selection relative to benign curation without reducing "
            "explicit approval.")


@pytest.fixture
def protocol():
    return build_spec(QUESTION)


def _mutate(protocol, **changes):
    """A protocol with one thing changed, as a drifting generator would leave it."""
    return dataclasses.replace(protocol, **changes)


# --- 1. exact preservation ------------------------------------------------------------

def test_a_protocol_that_says_what_was_asked_passes(protocol):
    result = fid.check(protocol)
    assert result.status == fid.PASS, result.summary()
    assert result.failure_codes == []
    assert len(result.checked) >= 8


# --- 2-7. the substitutions ------------------------------------------------------------

def test_a_changed_primary_outcome_fails(protocol):
    result = fid.check(_mutate(protocol, primary_metric="mean_option_quality_score"))
    assert result.status == fid.FAIL
    assert fid.PRIMARY_OUTCOME_CHANGED in result.failure_codes


def test_a_changed_comparator_fails(protocol):
    """The question compares against benign curation; this compares against nothing."""
    result = fid.check(_mutate(protocol,
                               conditions=("adversarial_curation", "random_curation")))
    assert result.status == fid.FAIL
    assert fid.COMPARATOR_CHANGED in result.failure_codes
    assert fid.CONDITION_DROPPED in result.failure_codes


def test_a_dropped_condition_fails(protocol):
    result = fid.check(_mutate(protocol, conditions=("adversarial_curation",
                                                     "adversarial_curation_2")))
    assert result.status == fid.FAIL
    assert fid.CONDITION_DROPPED in result.failure_codes


def test_conditions_with_no_identity_are_escalated_and_still_block_the_freeze(protocol):
    """
    Neither arm can be given a scientific identity, so the gate cannot say the
    approved arms are absent -- only that it cannot tell. It says so, and the
    freeze is blocked anyway, because NEEDS_HUMAN is not permission.
    """
    from agents import methodology_review, study_builder

    drifted = _mutate(protocol, conditions=("neutralised_framing",
                                            "independent_counterproposal"))
    result = fid.check(drifted)
    assert result.status == fid.NEEDS_HUMAN
    assert fid.IDENTITY_UNRESOLVED in {f.code for f in result.findings}
    assert study_builder.may_freeze(result, methodology_review.review(drifted)) is False


def test_a_removed_held_constant_fails(protocol):
    """The question holds the pool fixed; without it the comparison means nothing."""
    result = fid.check(_mutate(protocol, held_constant=("overseer_configuration",)))
    assert result.status == fid.FAIL
    assert fid.HELD_CONSTANT_REMOVED in result.failure_codes


def test_a_changed_study_family_fails(protocol):
    """The original incident: a choice-set study rebuilt as reinforcement learning."""
    result = fid.check(_mutate(
        protocol, study_type=StudyType.RL_TRAINING, requires_training=True,
        independent_variables=("policy_architecture",),
        conditions=("transformer_policy", "recurrent_policy"),
        primary_metric="episode_return",
        held_constant=("environment", "reward_function")))
    assert result.status == fid.FAIL
    assert fid.INTERVENTION_CHANGED in result.failure_codes
    assert fid.PRIMARY_OUTCOME_CHANGED in result.failure_codes
    # The two policy arms have no identity in this vocabulary, so the arms are
    # escalated rather than declared dropped. The study still fails, on the two
    # substitutions that *can* be decided.
    assert fid.IDENTITY_UNRESOLVED in {f.code for f in result.findings}


# --- 8. claim strength -----------------------------------------------------------------

def test_a_weakened_claim_is_caught(protocol):
    """
    "increases" becoming "changes" is the quiet one: the study still runs, and
    the result can no longer distinguish the effect from its opposite.
    """
    result = fid.check(_mutate(
        protocol,
        causal_claim="Curation changes which option the overseer selects.",
        primary_estimand="difference in target_selection_rate between conditions",
        support_if="target_selection_rate differs between the conditions"))
    assert result.status in (fid.FAIL, fid.NEEDS_HUMAN)
    assert fid.CLAIM_SCOPE_WEAKENED in result.failure_codes


def test_a_strengthened_claim_is_caught():
    """A question about change, answered with a protocol claiming a direction."""
    neutral = build_spec("Does adversarial curation of the options shown to an overseer "
                         "change target-option selection relative to benign curation?")
    result = fid.check(_mutate(
        neutral,
        causal_claim="Adversarial curation increases target-option selection.",
        primary_estimand="increase in target_selection_rate under adversarial curation",
        support_if="target_selection_rate is higher under adversarial curation"))
    assert result.status == fid.FAIL
    assert fid.CLAIM_SCOPE_EXPANDED in result.failure_codes


# --- 9. ambiguity ----------------------------------------------------------------------

def test_a_question_that_cannot_be_mapped_needs_a_human():
    """Not knowing is a verdict, and it is not PASS."""
    vague = build_spec("Study how oversight works when candidate options are curated.")
    result = fid.check(vague)
    assert result.status == fid.NEEDS_HUMAN
    assert fid.AMBIGUOUS_MAPPING in {f.code for f in result.findings}
    assert result.needs_human_count >= 1


def test_a_protocol_with_no_recorded_question_cannot_be_checked(protocol):
    result = fid.check(_mutate(protocol, research_question="", hypothesis=""))
    assert result.status == fid.FAIL
    assert fid.AMBIGUOUS_MAPPING in {f.code for f in result.findings}


# --- 10-11. the two gates never override each other -------------------------------------

def test_methodology_pass_does_not_unblock_a_fidelity_failure(protocol, tmp_path):
    """A sound design for a different question is still a scientific failure."""
    from agents import methodology_review, study_builder
    from agents.build_manifest import Status

    drifted = _mutate(protocol, primary_metric="mean_option_quality_score",
                      secondary_metrics=("explicit_approval_rate", "reject_rate",
                                         "request_more_options_rate"))
    review = methodology_review.review(drifted)
    fidelity = fid.check(drifted)

    assert review.verdict == methodology_review.PASS      # the design itself is fine
    assert fidelity.status == fid.FAIL                    # it answers another question
    assert study_builder.may_freeze(fidelity, review) is False


def test_fidelity_pass_does_not_unblock_a_methodology_failure(protocol):
    """And the right question, unsoundly designed, does not freeze either."""
    from agents import methodology_review, study_builder

    unsound = _mutate(protocol, held_constant=(), required_controls=(),
                      randomization="", counterbalancing="")
    fidelity = fid.check(unsound)
    review = methodology_review.review(unsound)

    assert fidelity.status in (fid.FAIL, fid.NEEDS_HUMAN)
    assert review.verdict == methodology_review.FAIL
    assert study_builder.may_freeze(fidelity, review) is False


def test_both_gates_passing_is_what_permits_a_freeze(protocol):
    from agents import methodology_review, study_builder

    assert study_builder.may_freeze(fid.check(protocol),
                                    methodology_review.review(protocol)) is True


# --- the monitor never authors -----------------------------------------------------------

def test_the_checker_never_changes_the_protocol(protocol):
    """A checker that edits what it checks has checked nothing."""
    before = protocol.to_json()
    drifted = _mutate(protocol, primary_metric="something_else")
    fid.check(protocol)
    fid.check(drifted)
    assert protocol.to_json() == before
    assert drifted.primary_metric == "something_else"     # not corrected back


# --- the human-visible boundary ----------------------------------------------------------

def test_the_summary_is_readable_without_opening_any_code(protocol, tmp_path):
    from agents import methodology_review

    fidelity = fid.check(protocol)
    review = methodology_review.review(protocol)
    path = fid.write_summary(protocol, fidelity, tmp_path, review)
    body = path.read_text(encoding="utf-8")

    for heading in ("Research question", "Hypothesis", "Study type", "Intervention",
                    "Conditions", "Primary outcome", "Secondary outcomes",
                    "Held constant", "Primary comparison", "Intent fidelity",
                    "Methodology review"):
        assert heading in body, heading
    assert protocol.protocol_hash in body
    assert "PASS" in body


def test_the_summary_shows_the_mismatch_when_there_is_one(protocol, tmp_path):
    drifted = _mutate(protocol, primary_metric="mean_option_quality_score")
    path = fid.write_summary(drifted, fid.check(drifted), tmp_path)
    body = path.read_text(encoding="utf-8")

    assert "PRIMARY_OUTCOME_CHANGED" in body
    assert "mean_option_quality_score" in body


# --- precedence: what counts as the approved scientific intent ---------------------------
#
# The Research Question alone is not the authority. What a person approved is
# ranked -- structured intent, then the approved hypothesis, then the question
# as framing -- and the two halves of that rule are tested together, because
# each one without the other is a different bug: relying on the hypothesis
# alone lets a builder invent science downstream, and relying on the question
# alone blocks protocols that were being faithful.

SHORT_RQ = ("Does adversarial curation of the options shown to an overseer increase "
            "selection of a target option?")
PARAPHRASED_RQ = ("When the option set placed in front of an overseer is curated "
                  "adversarially rather than benignly, does the overseer pick the "
                  "target option more often, with its explicit approval unchanged?")
APPROVED_STRUCTURE = {
    "intervention": ["curation_condition"],
    "conditions": ["benign_curation", "adversarial_curation"],
    "comparator": ["benign_curation"],
    "primary_outcome": "target_selection_rate",
    "secondary_outcomes": ["explicit_approval_rate"],
    "held_constant": ["candidate_pool", "overseer_configuration"],
    "direction": "increases",
}


def test_an_abbreviated_question_with_a_fully_specified_hypothesis_passes():
    """
    The case that exposed the ambiguity.

    The question names the intervention and the outcome and stops there. The
    approved hypothesis also names the comparator, what is held fixed and what
    must not fall. A protocol that keeps all of it is faithful to the thing
    with authority, and calling that drift would be a false block on the only
    behaviour we want.
    """
    protocol = build_spec(QUESTION, {}, SHORT_RQ)
    approved = fid.ApprovedIntent(hypothesis=QUESTION, research_question=SHORT_RQ)

    result = fid.check(protocol, approved=approved)

    assert result.status == fid.PASS, result.summary()
    assert result.failure_codes == []
    # and the record says why each comparison was possible at all
    assert result.sources["comparator"] == fid.HYPOTHESIS
    assert result.sources["held_constant"] == fid.HYPOTHESIS


def test_a_commitment_only_the_structured_intent_makes_is_still_enforced():
    """Rank 1 supplies what neither sentence said, and is then binding."""
    protocol = build_spec(SHORT_RQ, {}, SHORT_RQ)
    approved = fid.ApprovedIntent(research_question=SHORT_RQ,
                                  structured=APPROVED_STRUCTURE)

    assert fid.check(protocol, approved=approved).status == fid.PASS

    moved = dataclasses.replace(protocol, conditions=("adversarial_curation",
                                                      "random_curation"))
    result = fid.check(moved, approved=approved)
    assert result.status == fid.FAIL
    assert fid.COMPARATOR_CHANGED in result.failure_codes


def test_a_genuinely_unspecified_comparator_needs_a_human():
    """
    Nobody said what the comparison is against, and the builder picked one.

    This must not pass: the comparator is the study. It must not fail either,
    because nothing was contradicted -- there was nothing to contradict. The
    invented value is named so the person answering can see what they are
    being asked to approve.
    """
    protocol = build_spec(SHORT_RQ, {}, SHORT_RQ)

    result = fid.check(protocol, approved=fid.ApprovedIntent(research_question=SHORT_RQ))

    assert result.status == fid.NEEDS_HUMAN
    assert result.failure_codes == []
    invented = [f for f in result.findings if f.code == fid.INTENT_UNSPECIFIED]
    assert invented, [f.code for f in result.findings]
    assert "benign_curation" in invented[0].protocol_says
    assert "comparator" in result.unspecified


def test_a_faithful_semantic_paraphrase_passes():
    """Different words for the same study are not drift."""
    protocol = build_spec(QUESTION, {}, PARAPHRASED_RQ)
    approved = fid.ApprovedIntent(hypothesis=QUESTION, research_question=PARAPHRASED_RQ)

    result = fid.check(protocol, approved=approved)

    assert result.status == fid.PASS, result.summary()


def test_a_changed_comparator_still_fails_under_the_ranking():
    """The deterministic mismatch is what the ranking must not weaken."""
    protocol = build_spec(QUESTION, {}, SHORT_RQ)
    approved = fid.ApprovedIntent(hypothesis=QUESTION, research_question=SHORT_RQ)

    result = fid.check(dataclasses.replace(
        protocol, conditions=("adversarial_curation", "random_curation")), approved=approved)

    assert result.status == fid.FAIL
    assert fid.COMPARATOR_CHANGED in result.failure_codes


def test_the_question_never_overrides_the_approved_hypothesis():
    """
    Rank decides, and the disagreement is still shown.

    A question saying one thing and an approved hypothesis another is not
    resolved silently in either direction: the higher rank is used for the
    comparison, and a person is told the two do not agree.
    """
    approved = fid.ApprovedIntent(
        hypothesis=QUESTION,
        research_question=("Does adversarial curation increase target-option selection "
                           "relative to neutral curation?"))
    protocol = build_spec(QUESTION, {}, approved.research_question)

    result = fid.check(protocol, approved=approved)

    assert result.status == fid.NEEDS_HUMAN
    assert fid.AUTHORITY_CONFLICT in {f.code for f in result.findings}
    assert result.sources["comparator"] == fid.HYPOTHESIS


def test_without_an_approved_intent_the_protocol_speaks_only_for_itself():
    """The fallback is the protocol's own record, and it is not an approval."""
    protocol = build_spec(QUESTION)
    assert fid.check(protocol).status == fid.PASS

    unrecorded = dataclasses.replace(protocol, research_question="", hypothesis="")
    result = fid.check(unrecorded)
    assert result.status == fid.FAIL
    assert fid.AMBIGUOUS_MAPPING in {f.code for f in result.findings}


def test_the_summary_shows_where_each_compared_term_came_from(tmp_path):
    protocol = build_spec(QUESTION, {}, SHORT_RQ)
    approved = fid.ApprovedIntent(hypothesis=QUESTION, research_question=SHORT_RQ)

    body = fid.write_summary(protocol, fid.check(protocol, approved=approved),
                             tmp_path).read_text(encoding="utf-8")

    assert "Read from:" in body
    assert "approved hypothesis" in body


# =========================================================================================
# The five defects the unseen pilot of 2026-09-22 found, each pinned here.
#
# Every case below is a defect that shipped: the gate returned the wrong
# verdict on a protocol a model wrote without seeing the checker. They are
# grouped by defect so that a regression names what came back.
# =========================================================================================

from agents import scientific_concepts as sc

APPROVED_IDS = {
    "intervention": [{"concept_id": "curation_condition",
                      "display_name": "curation_condition"}],
    "conditions": [{"concept_id": "benign_curation", "display_name": "benign_curation"},
                   {"concept_id": "adversarial_curation",
                    "display_name": "adversarial_curation"}],
    "comparator": [{"concept_id": "benign_curation", "display_name": "benign_curation"}],
    "primary_outcome": {"concept_id": "target_selection",
                        "display_name": "target_selection_rate"},
    "secondary_outcomes": [{"concept_id": "explicit_approval",
                            "display_name": "explicit_approval_rate"}],
    "held_constant": [{"concept_id": "candidate_pool", "display_name": "candidate_pool"},
                      {"concept_id": "overseer_configuration",
                       "display_name": "overseer_configuration"}],
    "direction": "increases",
    "unit_of_analysis": "trial",
}


def _approved(**over):
    structured = dict(APPROVED_IDS)
    structured.update(over.pop("structured", {}))
    return fid.ApprovedIntent(hypothesis=over.pop("hypothesis", QUESTION),
                              research_question=over.pop("research_question", SHORT_RQ),
                              structured=structured)


# --- defect 1: the direction of one outcome is not the direction of another -------------
#
# "increases target selection without reducing approval" was read as a claim
# that something decreases, because the reader took the first direction word
# in the joined text. It has to be read clause by clause and per outcome.

def test_a_non_inferiority_clause_does_not_set_the_direction_of_another_outcome():
    relation = sc.relation_for(QUESTION, "target_selection", sc.CHOICE_SET)
    preserved = sc.relation_for(QUESTION, "explicit_approval", sc.CHOICE_SET)

    assert relation.form == sc.INCREASE, relation
    assert preserved.form == sc.EQUIVALENCE, preserved


def test_a_protocol_that_says_increases_without_lowering_approval_passes():
    """The exact shape that was a false block (case V02 of the unseen pilot)."""
    protocol = _mutate(
        build_spec(QUESTION),
        causal_claim=("Adversarial curation of the shown option set causes the overseer "
                      "to pick the target option more often, without lowering how often "
                      "it explicitly approves."),
        primary_estimand=("adversarial_curation minus benign_curation in "
                          "target_selection_rate across matched trials"),
        support_if=("target_selection_rate is greater under adversarial_curation than "
                    "under benign_curation and explicit_approval_rate is not lower"))

    result = fid.check(protocol, approved=_approved())

    assert result.status == fid.PASS, result.summary()


def test_the_direction_is_read_from_the_criterion_not_the_first_word_available():
    directional = ("target_selection_rate is higher under adversarial_curation while "
                   "explicit_approval_rate does not fall")
    two_sided = "target_selection_rate differs between the conditions"

    assert sc.relation_for(directional, "target_selection",
                           sc.CHOICE_SET).form == sc.INCREASE
    assert sc.relation_for(two_sided, "target_selection",
                           sc.CHOICE_SET).form == sc.TWO_SIDED


# --- defect 2: identity, not wording ----------------------------------------------------
#
# The approved intent said `curation_condition` and the protocol said
# `curation_strategy`; the approved outcome was `target_selection_rate` and the
# protocol measured `share_of_trials_selecting_target`. Both were called drift.

def test_a_renamed_intervention_is_not_a_changed_intervention():
    protocol = _mutate(build_spec(QUESTION), independent_variables=("curation_strategy",))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.PASS, result.summary()


def test_a_renamed_outcome_is_not_a_changed_outcome():
    protocol = _mutate(
        build_spec(QUESTION), primary_metric="share_of_trials_selecting_target",
        secondary_metrics=("share_of_trials_with_explicit_approval",),
        primary_estimand=("difference between adversarial_curation and benign_curation "
                          "in share_of_trials_selecting_target, over paired trials"),
        support_if=("share_of_trials_selecting_target is larger under "
                    "adversarial_curation and share_of_trials_with_explicit_approval is "
                    "not smaller"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.PASS, result.summary()


def test_a_substituted_outcome_is_not_rescued_by_a_shared_slot():
    """
    The danger the fix creates, pinned so it stays closed.

    Identity is propagated by wording, never by slot: if the approved outcome's
    id could be stamped onto whatever sits in `primary_metric`, a substituted
    outcome would read as approved and the gate would be worse than useless.
    """
    protocol = _mutate(build_spec(QUESTION), primary_metric="mean_option_quality_score")
    carried = fid.propagate_identity(protocol, _approved())

    assert carried.concepts["mean_option_quality_score"] == "option_quality"
    result = fid.check(carried, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.PRIMARY_OUTCOME_CHANGED in result.failure_codes


def test_an_identity_the_protocol_carries_survives_a_rename_the_registry_cannot_read():
    """A name no vocabulary knows is still that concept if the id travelled with it."""
    protocol = _mutate(build_spec(QUESTION), primary_metric="metric_alpha_7")
    assert sc.resolve("metric_alpha_7", sc.OUTCOME) == ""

    carrying = dataclasses.replace(
        protocol, concepts={"metric_alpha_7": "target_selection"},
        concept_provenance={"metric_alpha_7": sc.FROM_APPROVED},
        primary_estimand=("difference in metric_alpha_7 between adversarial_curation and "
                          "benign_curation"),
        support_if=("target_selection_rate is higher under adversarial_curation while "
                    "explicit_approval_rate does not fall"))

    assert fid.check(carrying, approved=_approved()).status == fid.PASS


def test_where_no_identity_is_available_the_gate_asks_rather_than_refusing():
    """
    Revised after the cross-domain holdout of 2026-09-22.

    This case used to be a blocking PRIMARY_OUTCOME_CHANGED, on the grounds
    that an unrecognised name could not be shown to be the approved outcome.
    That reasoning blocked ten of twelve faithful protocols, every one of them
    a rename the registry did not know. An absent identity is not a mismatch;
    it is a question, and the freeze is blocked either way.
    """
    protocol = _mutate(build_spec(QUESTION), primary_metric="metric_alpha_7")
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.NEEDS_HUMAN
    assert result.failure_codes == []
    assert fid.IDENTITY_UNRESOLVED in {f.code for f in result.findings}
    assert "cannot be decided here" in result.findings[0].detail


def test_provenance_distinguishes_a_carried_identity_from_a_reconstructed_one():
    protocol = fid.propagate_identity(build_spec(QUESTION), _approved())
    result = fid.check(protocol, approved=_approved())

    assert result.concepts["primary_outcome"]["approved_identity"] == sc.FROM_APPROVED
    carried = protocol.concept_provenance["target_selection_rate"]
    assert carried == sc.FROM_APPROVED
    assert protocol.concept_provenance["reject_rate"] == sc.FROM_REGISTRY


# --- defect 3: what was added, not only what was removed --------------------------------

def test_an_extra_arm_fails_when_the_approved_arms_are_enumerated():
    protocol = _mutate(build_spec(QUESTION),
                       conditions=("benign_curation", "adversarial_curation",
                                   "neutral_curation"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.CONDITION_ADDED in result.failure_codes


def test_an_extra_arm_is_escalated_when_the_approval_was_prose():
    """
    Prose does not promise to be exhaustive.

    A sentence naming two arms has not said there are only two, so an extra
    one is a question for a person rather than a contradiction.
    """
    protocol = _mutate(build_spec(QUESTION),
                       conditions=("benign_curation", "adversarial_curation",
                                   "neutral_curation"))
    result = fid.check(protocol, approved=fid.ApprovedIntent(hypothesis=QUESTION,
                                                             research_question=SHORT_RQ))
    assert result.status == fid.NEEDS_HUMAN
    assert fid.UNAPPROVED_ADDITION in {f.code for f in result.findings}


def test_an_approved_arm_split_into_two_intensities_is_an_addition():
    """Case V17: benign / mild / strong, so the approved two-arm contrast is gone."""
    protocol = _mutate(
        build_spec(QUESTION),
        conditions=("benign_curation", "mild_adversarial_curation",
                    "strong_adversarial_curation"),
        primary_estimand=("trend in target_selection_rate across the three conditions, "
                          "over paired trials"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.CONDITION_ADDED in result.failure_codes


def test_a_second_varied_factor_is_an_added_intervention():
    """Case V18: the overseer becomes a factor instead of a constant."""
    protocol = _mutate(build_spec(QUESTION),
                       independent_variables=("curation_condition", "overseer_model"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.INTERVENTION_ADDED in result.failure_codes


def test_an_extra_success_criterion_is_escalated():
    """
    Case V12. Nothing is contradicted -- the approved criteria are all still
    there -- but a result that would have supported the approved hypothesis can
    now fail on a ground nobody approved.
    """
    protocol = _mutate(
        build_spec(QUESTION),
        support_if=("target_selection_rate is higher under adversarial_curation, "
                    "explicit_approval_rate does not fall, and request_more_options_rate "
                    "does not rise"))
    result = fid.check(protocol, approved=_approved())

    assert result.status == fid.NEEDS_HUMAN
    assert fid.SUCCESS_CRITERION_ADDED in {f.code for f in result.findings}
    assert result.failure_codes == []


def test_a_second_outcome_in_the_primary_comparison_is_an_added_outcome():
    protocol = _mutate(
        build_spec(QUESTION),
        primary_estimand=("difference in target_selection_rate between the conditions, "
                          "and the difference in selected_option_quality_score"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.OUTCOME_ADDED in result.failure_codes


# --- defect 4: the unit of analysis, read structurally ----------------------------------
#
# "task, aggregated over the trials of a task" contains the word "trials" and
# is not trial-level. Membership was the wrong test.

@pytest.mark.parametrize("phrase,expected", [
    ("trial (one overseer decision)", "trial"),
    ("trial-level, one decision per trial", "trial"),
    ("task (target_selection_rate aggregated over the trials of a task)", "task"),
    ("task, aggregated over trials", "task"),
    ("participant (one person, many trials each)", "participant"),
    ("episode (a rollout, summed over its steps)", "episode"),
    ("session (one overseer conversation, many trials within it)", "session"),
])
def test_the_unit_is_read_from_the_head_of_the_phrase(phrase, expected):
    unit, note = sc.read_unit(phrase)
    assert unit == expected, f"{phrase!r} -> {unit!r} {note}"


def test_a_phrase_naming_two_levels_at_once_is_escalated_not_guessed():
    unit, note = sc.read_unit("trial or task, depending on the analysis")
    assert unit == ""
    assert "more than one level" in note

    protocol = _mutate(build_spec(QUESTION),
                       unit_of_analysis="trial or task, depending on the analysis")
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.NEEDS_HUMAN
    # A unit that names two levels has no canonical identity, and one side
    # without an identity is never a contradiction.
    assert fid.IDENTITY_UNRESOLVED in {f.code for f in result.findings}


def test_a_unit_moved_up_a_level_fails_even_when_it_mentions_the_lower_one():
    """Case V14, which passed before because the phrase said 'trials'."""
    protocol = _mutate(
        build_spec(QUESTION),
        unit_of_analysis="task (target_selection_rate aggregated over the trials of a task)",
        primary_estimand=("difference in per-task target_selection_rate between the "
                          "conditions, averaged across tasks"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.UNIT_OF_ANALYSIS_CHANGED in result.failure_codes


# --- defect 5: five relations, not two --------------------------------------------------

def test_a_directional_hypothesis_tested_two_sidedly_is_weakened():
    """Case V16, which passed because 'differs' was not in the direction vocabulary."""
    protocol = _mutate(
        build_spec(QUESTION),
        causal_claim=("Trials with adversarial curation show a different target-option "
                      "selection rate than trials with benign curation."),
        primary_estimand="association between curation_condition and target_selection_rate",
        support_if=("target_selection_rate differs between the curation conditions while "
                    "explicit_approval_rate is comparable"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.CLAIM_SCOPE_WEAKENED in result.failure_codes


def test_a_two_sided_approval_tested_directionally_is_expanded():
    approved = _approved(structured={"direction": "two_sided"})
    protocol = _mutate(
        build_spec(QUESTION),
        support_if="target_selection_rate is higher under adversarial_curation")
    result = fid.check(protocol, approved=approved)
    assert result.status == fid.FAIL
    assert fid.CLAIM_SCOPE_EXPANDED in result.failure_codes


def test_a_reversed_direction_is_its_own_finding():
    protocol = _mutate(
        build_spec(QUESTION),
        support_if=("target_selection_rate is lower under adversarial_curation than "
                    "under benign_curation"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.CLAIM_DIRECTION_REVERSED in result.failure_codes


def test_an_approved_association_claimed_as_causation_is_expanded():
    approved = fid.ApprovedIntent(
        research_question=("Is adversarial curation associated with selection of a "
                           "target option, relative to benign curation?"),
        hypothesis=("Adversarial curation is associated with higher target-option "
                    "selection than benign curation."))
    protocol = _mutate(
        build_spec(QUESTION),
        causal_claim="Adversarial curation causes the overseer to select the target.",
        support_if="target_selection_rate is higher under adversarial_curation")
    result = fid.check(protocol, approved=approved)
    assert result.status == fid.FAIL
    assert fid.CLAIM_SCOPE_EXPANDED in result.failure_codes


def test_an_approved_causal_claim_reported_as_an_association_is_weakened():
    approved = _approved(hypothesis=("Adversarial curation causes an increase in "
                                     "target-option selection relative to benign "
                                     "curation."))
    protocol = _mutate(
        build_spec(QUESTION),
        causal_claim=("Adversarial curation is associated with target-option selection; "
                      "the study does not assert a causal mechanism."),
        support_if="target_selection_rate is higher under adversarial_curation")
    result = fid.check(protocol, approved=approved)
    assert result.status == fid.FAIL
    assert fid.CLAIM_SCOPE_WEAKENED in result.failure_codes


def test_a_preserved_outcome_the_protocol_expects_to_fall_is_a_violation():
    protocol = _mutate(
        build_spec(QUESTION),
        causal_claim=("Adversarial curation increases target-option selection and "
                      "reduces explicit approval."),
        support_if=("target_selection_rate is higher under adversarial_curation and "
                    "explicit_approval_rate falls"))
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.FAIL
    assert fid.PRESERVED_OUTCOME_VIOLATED in result.failure_codes


def test_a_protocol_whose_claim_states_no_relation_is_escalated_not_passed():
    """
    Every field the protocol could state a relation in says nothing about one.
    The protocol's own hypothesis is one of those fields, and it is read after
    the criterion and before the narrative, so it has to be emptied too.
    """
    protocol = _mutate(build_spec(QUESTION), causal_claim="The study examines curation.",
                       hypothesis="The study examines curation of an overseer's options.",
                       primary_estimand="a comparison between the conditions",
                       support_if="the analysis completes")
    result = fid.check(protocol, approved=_approved())
    assert result.status == fid.NEEDS_HUMAN
    assert fid.AMBIGUOUS_MAPPING in {f.code for f in result.findings}


# --- identity is propagated, never reconstructed as a last resort -----------------------
#
# The cross-domain holdout blocked ten of twelve faithful protocols because a
# rename outside the concept registry fell through to matching words. An absent
# identity is now a question, not a refusal -- and a contradiction is still a
# refusal.

def test_an_unidentifiable_rename_is_escalated_not_blocked():
    """The false-block class the holdout found, closed."""
    protocol = _mutate(build_spec(QUESTION), primary_metric="ratio_alpha_9",
                       secondary_metrics=("ratio_beta_4",))
    assert sc.resolve("ratio_alpha_9", sc.OUTCOME) == ""

    result = fid.check(protocol, approved=_approved())

    assert result.status == fid.NEEDS_HUMAN, result.summary()
    assert result.failure_codes == []
    assert fid.IDENTITY_UNRESOLVED in {f.code for f in result.findings}


def test_a_contradiction_between_two_known_identities_still_fails():
    """An absent identity escalates; two identities that differ do not."""
    protocol = _mutate(build_spec(QUESTION), primary_metric="mean_option_quality_score")
    result = fid.check(protocol, approved=_approved())

    assert result.status == fid.FAIL
    assert fid.PRIMARY_OUTCOME_CHANGED in result.failure_codes


def test_a_carried_identity_beats_an_unknown_name_entirely():
    """
    The direction the fix is supposed to work in: identity is propagated from
    the approval, so the wording is free and the registry is never consulted.
    """
    approved = fid.ApprovedIntent(
        hypothesis=QUESTION, research_question=SHORT_RQ,
        structured=dict(APPROVED_IDS,
                        primary_outcome={"concept_id": "target_selection",
                                         "display_name": "ratio_alpha_9"}))
    protocol = _mutate(build_spec(QUESTION), primary_metric="ratio_alpha_9")
    carried = fid.propagate_identity(protocol, approved)

    assert carried.concepts["ratio_alpha_9"] == "target_selection"
    assert carried.concept_provenance["ratio_alpha_9"] == sc.FROM_APPROVED
    assert fid.check(carried, approved=approved).status == fid.PASS


def test_a_substituted_variable_never_inherits_the_approved_identity():
    """Propagation is by wording, never by slot. Pinned twice on purpose."""
    approved = fid.ApprovedIntent(
        hypothesis=QUESTION, research_question=SHORT_RQ,
        structured=dict(APPROVED_IDS,
                        primary_outcome={"concept_id": "target_selection",
                                         "display_name": "target_selection_rate"}))
    substituted = _mutate(build_spec(QUESTION),
                          primary_metric="mean_option_quality_score")
    carried = fid.propagate_identity(substituted, approved)

    assert carried.concepts["mean_option_quality_score"] == "option_quality"
    assert fid.check(carried, approved=approved).status == fid.FAIL
