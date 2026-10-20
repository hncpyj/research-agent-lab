"""
Scientific identity is propagated, scoped, or absent — never guessed.

The defect these pin: a memory outcome named `delayed_recall_score` resolved to
`classification_accuracy`, because that concept accepts the stem `recall` as in
precision-and-recall. The approved side carried its correct identity, the
protocol side was handed a confident wrong one, and the gate saw two known
identities that differed and called it a contradiction. A faithful protocol was
blocked by a coincidence of English (X02, X13, X19, 2026-09-22).

The rule that replaces it, in order:

    1. an identity the approved intent propagated, if there is one;
    2. otherwise deterministic resolution scoped to domain *and* kind;
    3. otherwise unresolved, which is NEEDS_HUMAN and never FAIL.

FAIL requires two identities that are both resolved and known to differ —
including the case where one of them resolves unambiguously in a *different*
field, which is the original incident of a choice-set study rebuilt as
reinforcement learning.
"""
import dataclasses

import pytest

from agents import intent_fidelity as fid
from agents import scientific_concepts as sc
from agents.experiment_agent import build_spec

QUESTION = ("Holding the underlying candidate pool fixed, adversarial curation increases "
            "target-option selection relative to benign curation without reducing "
            "explicit approval.")
SHORT_RQ = ("Does adversarial curation of the options shown to an overseer increase "
            "selection of a target option?")

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


def approved(**over):
    structured = dict(APPROVED_IDS)
    structured.update(over.pop("structured", {}))
    return fid.ApprovedIntent(hypothesis=over.pop("hypothesis", QUESTION),
                              research_question=over.pop("research_question", SHORT_RQ),
                              structured=structured, domain=over.pop("domain", ""))


def mutate(protocol, **changes):
    return dataclasses.replace(protocol, **changes)


# --- 1. a propagated identity survives any wording --------------------------------------

def test_an_approved_concept_id_survives_different_display_wording():
    intent = approved(structured={"primary_outcome": {
        "concept_id": "target_selection", "display_name": "share_of_trials_on_target"}})
    protocol = mutate(build_spec(QUESTION), primary_metric="share_of_trials_on_target",
                      primary_estimand=("difference in share_of_trials_on_target between "
                                        "adversarial_curation and benign_curation"),
                      support_if=("target_selection_rate is higher under "
                                  "adversarial_curation while explicit_approval_rate "
                                  "does not fall"))
    carried = fid.propagate_identity(protocol, intent)

    assert carried.concepts["share_of_trials_on_target"] == "target_selection"
    assert carried.concept_provenance["share_of_trials_on_target"] == sc.FROM_APPROVED
    assert fid.check(carried, approved=intent).status == fid.PASS


# --- 2. a kind never resolves another kind ----------------------------------------------

@pytest.mark.parametrize("term,its_kind,other_kind", [
    ("benign_curation", sc.CONDITION, sc.OUTCOME),
    ("target_selection_rate", sc.OUTCOME, sc.CONDITION),
    ("candidate_pool", sc.CONSTANT, sc.INTERVENTION),
    ("curation_condition", sc.INTERVENTION, sc.CONSTANT),
    ("trial", sc.UNIT, sc.OUTCOME),
])
def test_a_token_from_one_kind_does_not_resolve_another(term, its_kind, other_kind):
    assert sc.resolve(term, its_kind, sc.CHOICE_SET)
    assert sc.resolve(term, other_kind, sc.CHOICE_SET) == ""


def test_the_resolver_refuses_to_answer_without_a_kind():
    assert sc.resolve("benign_curation", "", sc.CHOICE_SET) == ""
    assert sc.resolve("benign_curation", None, sc.CHOICE_SET) == ""


# --- 3. a token from one domain never resolves another ----------------------------------

def test_a_memory_outcome_is_not_a_classifier_metric():
    """The defect, stated as the test that would have caught it."""
    assert sc.resolve("delayed_recall_score", sc.OUTCOME, sc.ML_EVAL) == \
        "classification_accuracy"
    assert sc.resolve("delayed_recall_score", sc.OUTCOME, sc.CHOICE_SET) == ""
    assert sc.resolve("delayed_recall_score", sc.OUTCOME, "") == ""
    assert sc.resolve("proportion_of_items_correctly_produced_at_long_delay_cued_recall",
                      sc.OUTCOME, "") == ""


def test_an_unknown_domain_admits_only_field_independent_concepts():
    # A unit of analysis means the same thing in every field.
    assert sc.resolve("participant_learner", sc.UNIT, "") == "participant"
    # Everything else abstains.
    assert sc.resolve("episode_return", sc.OUTCOME, "") == ""
    assert sc.resolve("benign_curation", sc.CONDITION, "") == ""


def test_a_foreign_identity_is_only_claimed_when_the_field_is_known():
    assert sc.resolve_foreign("policy_architecture", sc.INTERVENTION, sc.CHOICE_SET) == \
        ("policy_architecture", sc.ML_EVAL)
    # Unknown field: no inference is safe, so none is drawn.
    assert sc.resolve_foreign("delayed_recall_score", sc.OUTCOME, "") == ("", "")


# --- 4. an unknown concept asks rather than refuses -------------------------------------

def test_an_unknown_concept_is_escalated_not_blocked():
    protocol = mutate(build_spec(QUESTION), primary_metric="index_kappa_7")
    assert sc.resolve("index_kappa_7", sc.OUTCOME, sc.CHOICE_SET) == ""

    result = fid.check(protocol, approved=approved())

    assert result.status == fid.NEEDS_HUMAN
    assert result.failure_codes == []
    assert fid.IDENTITY_UNRESOLVED in {f.code for f in result.findings}


def test_an_unresolvable_unit_on_either_side_is_escalated():
    protocol = mutate(build_spec(QUESTION),
                      unit_of_analysis="trial or task, depending on the analysis")
    result = fid.check(protocol, approved=approved())

    assert result.status == fid.NEEDS_HUMAN
    assert fid.UNIT_OF_ANALYSIS_CHANGED not in result.failure_codes
    assert fid.IDENTITY_UNRESOLVED in {f.code for f in result.findings}


# --- 5. two known identities that differ still fail --------------------------------------

def test_two_resolved_identities_that_differ_fail():
    protocol = mutate(build_spec(QUESTION), primary_metric="mean_option_quality_score")
    result = fid.check(protocol, approved=approved())

    assert result.status == fid.FAIL
    assert fid.PRIMARY_OUTCOME_CHANGED in result.failure_codes


def test_a_study_rebuilt_in_another_field_still_fails():
    """
    The original incident. Every term belongs to another field, so nothing
    resolves in this one -- but each resolves unambiguously in that one, and
    two identities in two fields are two identities that differ.
    """
    from agents.study_protocol import StudyType

    rebuilt = mutate(build_spec(QUESTION), study_type=StudyType.RL_TRAINING,
                     requires_training=True,
                     independent_variables=("policy_architecture",),
                     conditions=("transformer_policy", "recurrent_policy"),
                     primary_metric="episode_return",
                     held_constant=("environment", "reward_function"))
    result = fid.check(rebuilt, approved=approved())

    assert result.status == fid.FAIL
    assert fid.INTERVENTION_CHANGED in result.failure_codes
    assert fid.PRIMARY_OUTCOME_CHANGED in result.failure_codes
    assert "ml eval" in " ".join(f.detail for f in result.findings)


# --- 6. identity is never inherited by position -----------------------------------------

def test_a_substituted_variable_does_not_inherit_the_approved_id_by_slot():
    intent = approved()
    substituted = mutate(build_spec(QUESTION),
                         primary_metric="mean_option_quality_score")
    carried = fid.propagate_identity(substituted, intent)

    assert carried.concepts["mean_option_quality_score"] == "option_quality"
    assert "target_selection" not in carried.concepts.values()
    assert fid.check(carried, approved=intent).status == fid.FAIL


# --- 7-9. the choice-set domain still behaves ---------------------------------------------

def test_a_faithful_terminology_change_in_this_domain_passes():
    protocol = mutate(
        build_spec(QUESTION), independent_variables=("curation_strategy",),
        primary_metric="share_of_trials_selecting_target",
        secondary_metrics=("share_of_trials_with_explicit_approval",),
        primary_estimand=("difference in share_of_trials_selecting_target between "
                          "adversarial_curation and benign_curation, over paired trials"),
        support_if=("share_of_trials_selecting_target is larger under "
                    "adversarial_curation and share_of_trials_with_explicit_approval is "
                    "not smaller"))
    result = fid.check(protocol, approved=approved())

    assert result.status == fid.PASS, result.summary()


def test_a_changed_comparator_fails():
    protocol = mutate(build_spec(QUESTION),
                      conditions=("adversarial_curation", "random_curation"))
    result = fid.check(protocol, approved=approved())

    assert result.status == fid.FAIL
    assert fid.COMPARATOR_CHANGED in result.failure_codes


def test_a_changed_primary_outcome_fails():
    protocol = mutate(build_spec(QUESTION), primary_metric="reject_rate")
    result = fid.check(protocol, approved=approved())

    assert result.status == fid.FAIL
    assert fid.PRIMARY_OUTCOME_CHANGED in result.failure_codes


# --- 10. the domain comes from the study, not from a guess --------------------------------

def test_the_domain_follows_the_scaffold_and_is_unknown_when_it_should_be():
    assert sc.domain_of(build_spec(QUESTION)) == sc.CHOICE_SET
    assert sc.domain_of("controlled_llm") == sc.CHOICE_SET
    assert sc.domain_of("rl_training") == sc.ML_EVAL
    assert sc.domain_of("something_nobody_registered") == ""


def test_an_approved_intent_may_state_its_own_domain():
    intent = approved(domain=sc.CHOICE_SET)
    assert fid.check(build_spec(QUESTION), approved=intent).status == fid.PASS
