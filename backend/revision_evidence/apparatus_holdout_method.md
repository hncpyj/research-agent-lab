# Apparatus-integrity 24-mutation holdout: method and item-level accounting

## Frozen sources

- `research_logs/raw/20260922_apparatus_holdout_v4.json` — 24 opaque mutation definitions.
- `research_logs/raw/20260922_apparatus_labels_v4.json` — frozen semantic labels, rationales, isolation statement, and label digest.
- `research_logs/raw/20260922_apparatus_eval_v4.jsonl` — integrity-enabled and integrity-disabled outcomes per mutation.
- `research_logs/raw/20260922_apparatus_totals_v4.json` — recorded aggregate counts.
- `research_logs/raw/20260922_hardening_freeze_v4.json` — sealed artifact hashes and frozen component hashes.
- `research_logs/runs/20260922_1501_apparatus_holdout.md` and `research_logs/runs.jsonl` — contemporaneous method, exact escaped IDs, limitations, and interpretation.

The holdout, label, and evaluation files each contain exactly 24 IDs, M01–M24, with identical sets. No item was excluded.

## Generation, isolation, and labelling

The generator was `claude-opus-5`. The frozen record says it could read only five apparatus files copied outside the repository and could not read the checkers, `build_manifest`, tests, the earlier F-C5 mutation, or expected detection codes. It generated 18 behavior-changing and 6 behavior-preserving single-file edits, shuffled under opaque IDs without recording category. The exact model version, generation prompt, decoding settings, and seed are **UNKNOWN**.

After generation, the 24 semantic labels were assigned by hand from each diff and frozen before the gate ran. Behavior-changing labels name a damaged guarantee. The individual label author is **UNKNOWN** and no independent adjudication is recorded. Label digest: `49b4261f89f3ec21`.

Each mutation was replayed twice: first through the production chain with the original sealed manifest; then with the manifest re-sealed around the mutated file, which makes content integrity pass by construction and exposes the remaining safeguards. The repository retains the outputs and method description, but no standalone source file for this 24-case replay driver was found; its exact executable path is therefore **UNKNOWN**.

## Verified aggregate claims

| Claim | Item-level result |
|---|---:|
| Behavior-changing mutations | 18 |
| Behavior-preserving mutations | 6 |
| Behavior-changing stopped with integrity enabled | 18/18 |
| Behavior-changing accepted by the remaining stack with integrity disabled | 15/18 |
| Behavior-changing still stopped elsewhere | 3/18 |
| Behavior-preserving edits refused by strict content integrity | 6/6 |

All 24 mutations were stopped at `SCIENTIFIC_CONFORMANCE` with integrity enabled, before execution. With integrity disabled, the exact three behavior-changing mutations still stopped were:

- **M04** (`evaluate.py`): `RESULT_CONFORMANCE` detected a summary that silently dropped the first trial.
- **M07** (`curation.py`): `SOFTWARE_PREFLIGHT` detected benign-arm wording changed to adversarial wording.
- **M10** (`choice_set.py`): `RESULT_CONFORMANCE` detected target-selection counting changed from target selection to any selection.

The other 15 behavior-changing IDs are M02, M05, M06, M08, M14, M15, M16, M17, M18, M19, M20, M21, M22, M23, and M24. Their counterfactual rows record no remaining detection and no pre-execution halt; the contemporaneous run report states that they escaped every remaining layer and produced accepted results.

The six behavior-preserving edits are M01, M03, M09, M11, M12, and M13. Strict hash binding refused all six. The run explicitly treats this as a valid-work cost, not a semantic false detection by the hash mechanism.

## Export notes

`revision_evidence/apparatus_holdout_24_mutations.csv` contains the exact before/after fragments, frozen label and rationale, enabled/disabled first-detection layers, and accepted-result status. For the disabled arm, `ACCEPTED_BY_REMAINING_STACK` is used only when the frozen row records no remaining detector and `without_integrity_halted_before_execution: false`; the run Markdown supplies the statement that those behavior-changing cases produced accepted results.
