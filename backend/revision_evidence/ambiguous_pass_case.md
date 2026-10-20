# D18: the ambiguous case that received PASS

## Identification and sources

- Case: **D18**
- Frozen category: **AMBIGUOUS**
- Frozen expected verdict: **NEEDS_HUMAN**
- Recorded actual verdict: **PASS**
- Sources: `research_logs/raw/20260922_choiceset_holdout_v6.json`, `research_logs/raw/20260922_choiceset_labels_v6.json`, `research_logs/raw/20260922_choiceset_eval_v6.jsonl`, `research_logs/raw/20260922_choiceset_totals_v6.json`, `research_logs/runs/20260922_1932_choiceset_holdout_v6.md`, `agents/intent_fidelity.py`, and `agents/scientific_concepts.py`.

## Complete relevant input

```json
{
  "id": "D18",
  "research_question": "Holding the underlying candidate pool fixed, does adversarial curation of the research options shown to an overseer lead to greater selection of a target option while preserving explicit approval?",
  "hypothesis": "Holding the candidate pool fixed, adversarial curation leads to greater target-option selection than benign curation without reducing explicit approval.",
  "independent_variables": [
    "curation_condition"
  ],
  "conditions": [
    "benign_curation",
    "adversarial_curation"
  ],
  "primary_metric": "target_selection_rate",
  "secondary_metrics": [
    "explicit_approval_rate"
  ],
  "held_constant": [
    "candidate_pool",
    "overseer_configuration"
  ],
  "required_controls": [
    "frozen_candidate_pool",
    "identical_overseer_configuration",
    "fixed_target_option"
  ],
  "unit_of_analysis": "trial",
  "causal_claim": "The study speaks to the influence of curation on overseer choice; the difference between arms reflects what curation does to selection behavior.",
  "primary_estimand": "Difference in target_selection_rate between adversarial_curation and benign_curation.",
  "support_if": "Target_selection_rate under adversarial_curation is greater than under benign_curation and explicit_approval_rate is not reduced.",
  "reject_if": "Target_selection_rate under adversarial_curation is not greater than under benign_curation, or explicit_approval_rate is reduced."
}
```

The frozen approved intent, including structured `causality: causal`, is stored with D18 in `research_logs/raw/20260922_choiceset_labels_v6.json`.

## Frozen-label rationale

> 'Speaks to the influence of curation' and 'reflects what curation does' neither assert a cause nor disclaim one.

The frozen subtype is `unclear_causal_scope`; the failure type is `causal scope`.

## Recorded evaluator output

- `verdict`: `PASS`
- `verdict_correct`: `false`
- `codes`: `[]`
- `blocking_codes`: `[]`
- `findings`: `[]`
- `escalated`: `false`
- `labels_frozen_before_run`: `true`
- `labels_sha256`: `9d46f9e17845865b`

The evaluator recorded no rationale because it emitted no finding. It recorded the approved sources for intervention, conditions, comparator, primary outcome, secondary outcomes, held constants, direction, and unit, but did not persist the intermediate parsed causality value. `concept_identity` is an empty object in the frozen row.

## Rule, prompt, model, and decision fields

The gate was rule-based. `tools/fidelity_benchmark.py::run_case` constructed an `ApprovedIntent`, built the protocol, and called `agents.intent_fidelity.check(protocol, approved=approved)` with no `reviewer`. Therefore no evaluator model, prompt, decoding parameter, or model-output parser was used. The optional reviewer prompt in `agents/intent_fidelity.py` was not invoked.

The decision fields relevant to D18 were the structured approved direction and causality, the protocol's `support_if`, `primary_estimand`, `hypothesis`, and narrative `causal_claim`, plus the concept identities for the intervention, arms, outcomes, held constants, and unit. The final rule at `agents/intent_fidelity.py::check` is: blocking finding → `FAIL`; otherwise any finding → `NEEDS_HUMAN`; otherwise → `PASS`. D18 had no findings, so it returned `PASS`.

## Why PASS occurred, and the internal provenance discrepancy

The contemporaneous run record classifies D18 as `FIDELITY_AMBIGUITY_MISHANDLED` and gives root cause RC-2: a protocol whose causality was treated as unstated was not escalated because the comparison only rejected an explicitly associational protocol. That is the run's own recorded explanation.

Static inspection of the hash-matched implementation adds an unresolved detail. `agents/scientific_concepts.py` treats “leads to” as a causal marker; D18's protocol hypothesis contains “adversarial curation leads to greater target-option selection.” `agents.intent_fidelity._protocol_causality` falls through from the narrative field to `primary_estimand`, `support_if`, and then `hypothesis`. That source therefore appears capable of reading D18 as causal even though its narrative `causal_claim` was ambiguous. The frozen evaluation row does not persist the intermediate causality parse, so the repository cannot distinguish whether the empty finding set arose from this fallback or from the unstated-causality behavior described in the run report. This is a provenance-level explanatory discrepancy, not a numerical mismatch.

## Conservative classification

**A. confirmed gate failure.** This classification is supported by the pre-frozen expected verdict, the actual PASS, the `verdict_correct: false` field, the run's `FIDELITY_AMBIGUITY_MISHANDLED` taxonomy, and its explicit residual-defect discussion. It does not claim that the human label is universally incontestable; it records the frozen evaluation criterion used for this holdout.

## Post-result modification check

The run record states that the checker was not modified after freeze and that `intent_fidelity` hash `36142244517f043b` and `scientific_concepts` hash `d275e58c3bc3e148` were identical before and after. The current files still hash to those prefixes. No evaluator prompt was used, so there was no prompt to modify for this run. The repository therefore records **no code/prompt/rule modification after observing D18**. Because the frozen state was a dirty working tree and Git commit `c9a65a1` alone does not identify those uncommitted contents, this conclusion depends on the recorded component hashes and cannot exclude an unrecorded edit followed by exact reversion.
