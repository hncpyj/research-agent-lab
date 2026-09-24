# Intent Fidelity implementation provenance for the 42-case holdout

## Exact implementation identity

| Role | Source | Frozen hash prefix |
|---|---|---|
| Gate and verdict composition | `agents/intent_fidelity.py` | `36142244517f043b` |
| Scientific concept, unit, relation, and causality reader | `agents/scientific_concepts.py` | `d275e58c3bc3e148` |
| Case-to-protocol construction and benchmark accounting | `tools/fidelity_benchmark.py` | not recorded in the component-hash block |
| Frozen approved intent and labels | `research_logs/raw/20260922_choiceset_labels_v6.json` | recorded label digest `9d46f9e17845865b` |
| Freeze record | `research_logs/raw/20260922_evidence_freeze_v6.json` | component hashes above |
| Final item-level outputs | `research_logs/raw/20260922_choiceset_eval_v6.jsonl` | every row repeats the component hashes |

The run metadata names Git commit `c9a65a1` and explicitly says the working tree was dirty. Consequently, the component content hashes—not the commit alone—identify the evaluated implementation. The present copies of `agents/intent_fidelity.py` and `agents/scientific_concepts.py` still match the recorded prefixes.

## Functions/classes and evaluator type

- `tools.fidelity_benchmark.run_case`: constructs `ApprovedIntent`, creates a `StudyProtocol`, and calls the production gate.
- `agents.intent_fidelity.ApprovedIntent` / `StructuredIntent`: ranked approved-source representation.
- `agents.intent_fidelity.read_intent`: resolves structured intent, approved hypothesis, and research question in precedence order.
- `agents.intent_fidelity.check`: performs the comparisons and composes PASS/FAIL/NEEDS_HUMAN.
- `agents.scientific_concepts.resolve`, `resolve_all`, `read_unit`, `relation_from_fields`, and `causality`: identity and relation readers used by the gate.

Evaluator type: **rule-based** for this holdout. The file supports an optional LLM reviewer, but `run_case` passes no reviewer. The generator model `claude-opus-5` created cases; it did not decide verdicts.

## Model, prompt, decoding, and parser

- Evaluator model identifier: **not applicable**.
- Evaluator prompt/template: **not applicable**.
- Evaluator decoding parameters: **not applicable**.
- Model-output parser: **not applicable**.
- Optional unused reviewer: `_REVIEWER_SYSTEM` plus `_ask_a_reviewer`, JSON `mismatches` parser, `max_tokens=800`, `temperature=0.0`. It was not used in the 42-case path.
- Deterministic parser: protocol field construction in `tools/fidelity_benchmark.py`, then concept/relation parsing in `agents/scientific_concepts.py` and comparison in `agents/intent_fidelity.py`.

## Executable decision rule

`check` gathers findings across intervention, conditions, comparator, primary/secondary outcomes, held constants, claim scope, internal consistency, generality, success criteria, required controls, unit, unapproved decisions, authority conflicts, and unreadable mappings.

1. If any finding's code is in `_BLOCKING`, status is `FAIL`.
2. Else if any finding exists, status is `NEEDS_HUMAN`.
3. Else status is `PASS`.
4. An optional reviewer, if supplied and the deterministic status is PASS, may only add doubts and raise PASS to NEEDS_HUMAN. It cannot clear a deterministic mismatch. No reviewer was supplied here.

`IDENTITY_UNRESOLVED`, `AMBIGUOUS_MAPPING`, `INTENT_UNSPECIFIED`, `UNAPPROVED_ADDITION`, `SUCCESS_CRITERION_ADDED`, `CLAIM_SCOPE_GENERALISED`, `CLAIM_INTERNALLY_INCONSISTENT`, and `AUTHORITY_CONFLICT` are non-blocking in this frozen implementation unless a separate blocking finding co-occurs.

## Relevant configuration and final development modification

The approved intent is `choice_set_approved_v2`, hash `cf91789a1202c3a7`, with causal direction and enumerated intervention, arms, comparator, primary/secondary outcomes, held constants, and unit. The freeze/run records list the final development changes: evidence-bounded concept claiming, generic-stem restrictions, two-part evidence for candidate-pool identity, head-word unit reading, broader relation vocabulary, claim-field precedence, difference-estimand neutrality, narrative causal-claim restrictions, field-precedence causality, internal-consistency checks, and non-blocking generality escalation. No holdout-derived term was added to the registry.

The run record says the resolver/relation reader was changed, 24 regression tests were added, the system was re-hashed and frozen, and only then the 42-case set was generated and labelled. It records timestamp `2026-09-22T19:32:03+01:00`, commit `c9a65a1`, dirty working tree, frozen label digest, and component hashes. `labels_frozen_before_running_checker` is true, and every result row repeats `labels_frozen_before_run: true`.

## Architecture statement versus executable logic

Architectural statement in the current paper: “Ambiguous identity mappings are escalated rather than silently certified.”

Recorded executable qualifications:

- An unresolved/ambiguous identity finding is non-blocking and produces NEEDS_HUMAN only when no blocking finding is also present. If a blocking mismatch co-occurs, the overall verdict is FAIL.
- The statement is about identity mappings, not every kind of semantic ambiguity. In the frozen 8-case ambiguous subset, five escalated, two failed, and D18 passed.
- D18 was a causal-scope ambiguity, not an identity-mapping ambiguity. It therefore does not numerically falsify the narrowly worded identity statement, but it shows that the architecture sentence must not be generalized to “all ambiguity is escalated.”
- The code's optional reviewer can only escalate a clean deterministic PASS, but it was absent in this run.

Sources: `agents/intent_fidelity.py`, `agents/scientific_concepts.py`, `tools/fidelity_benchmark.py`, `research_logs/raw/20260922_choiceset_labels_v6.json`, `research_logs/raw/20260922_evidence_freeze_v6.json`, `research_logs/raw/20260922_choiceset_eval_v6.jsonl`, `research_logs/runs/20260922_1932_choiceset_holdout_v6.md`, and `research_logs/runs.jsonl`.
