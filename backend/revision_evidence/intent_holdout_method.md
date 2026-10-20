# Intent-fidelity 42-case fresh holdout: method and accounting

## Scope and frozen sources

This is evidence extraction only. No case was regenerated and the gate was not rerun. The exact sources are:

- `research_logs/raw/20260922_choiceset_holdout_v6.json` — 42 generated protocol variants.
- `research_logs/raw/20260922_choiceset_labels_v6.json` — frozen labels, rationales, approved intent, and freeze metadata.
- `research_logs/raw/20260922_choiceset_eval_v6.jsonl` — one recorded evaluator result per case.
- `research_logs/raw/20260922_choiceset_totals_v6.json` — recorded aggregate accounting.
- `research_logs/raw/20260922_evidence_freeze_v6.json` — component hashes and the final development rules.
- `research_logs/runs/20260922_1932_choiceset_holdout_v6.md` — contemporaneous method, limitations, and interpretation.
- `research_logs/runs.jsonl` — machine-readable run index entry for `20260922_1932_choiceset_holdout_v6`.

All three item-level files contain exactly 42 IDs, D01–D42, with identical ID sets. Therefore every generated case is present in the label file and final evaluation log; no case-level exclusion is recorded.

## Verified complete outcome matrix

| Frozen category | n | PASS | FAIL | NEEDS_HUMAN |
|---|---:|---:|---:|---:|
| Drifted | 18 | 0 | 14 | 4 |
| Faithful | 16 | 9 | 1 | 6 |
| Ambiguous | 8 | 1 | 2 | 5 |
| **Total** | **42** | **10** | **17** | **15** |

Exact agreement with the pre-specified verdict is **28/42**. The actual `NEEDS_HUMAN` count is **15/42**. These values agree across `20260922_choiceset_totals_v6.json`, the item-level JSONL, the run Markdown, and the manuscript draft inspected during extraction.

## Generation and development separation

The frozen label record identifies `claude-opus-5` as the case generator. It records that the generator read no file on the machine and saw neither the checker nor prior holdouts, regressions, failure descriptions, or expected code. It was given the approved intent and protocol field list and asked to cover required variation types while emitting opaque IDs without recording which case was which. The run record says development changes and 24 regression tests were completed before the system was re-hashed and this fresh set was generated.

The repository does not record a provider model version, decoding settings, random seed, or full generation prompt. Those fields are therefore **UNKNOWN**. The recorded separation is generator isolation from local files/checkers and opaque case IDs; it is not evidence of an independently administered holdout.

## Retention and labelling

Every one of the 42 generated IDs appears once in the frozen labels and once in the final evaluation log. All are marked retained in the CSV because no exclusion field or missing ID exists. The label record states that cases were hand-labelled from case content and the approved intent, with a reason, drift type, failure type, and clear-substitution flag before the gate was run. It records `labels_frozen_before_running_checker: true`; each evaluation row repeats `labels_frozen_before_run: true` and label digest `9d46f9e17845865b`.

The individual human label author is **UNKNOWN** from the repository. Independent label adjudication is not recorded. The run's threats section refers to “the author's” labels, but it does not identify a person or a second labeler.

## Evaluation boundary

The generator model did not make the verdicts. The production intent-fidelity gate was deterministic for this run. The evaluator received the approved structured intent and each frozen protocol override. No optional LLM reviewer was passed by `tools/fidelity_benchmark.py::run_case`. The exact implementation and hash evidence are detailed in `intent_fidelity_implementation.md`.

## Export

`revision_evidence/intent_holdout_42_cases.csv` contains one row per retained case, the complete protocol fragment as compact JSON, the frozen rationale, actual findings, and a source-path column. Missing metadata is written as `UNKNOWN` rather than inferred.
