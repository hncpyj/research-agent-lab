# Failure corpus

Real failures, kept as regression cases. A case is never deleted because the
bug is fixed: the fix is the reason to keep it. Each one records what happened,
whether anything detected it at the time, and what would have been believed if
nothing had.

| ID | Failure | Detected then? | Would it have produced an invalid result? | Labels | Now |
|---|---|---|---|---|---|
| F1 | Choice-set curation study built as a MiniGrid RL experiment | recorded as a critical degradation, generation continued | yes — a result about an unrelated task | `WRONG_EXPERIMENT_FAMILY` `INTENT_DRIFT` | `UnsupportedExperimentError` before any file is written; protocol names the family |
| F2 | AG News resolved as the dataset for a study that needs none | recorded as critical, generation continued | yes | `DATASET_SUBSTITUTION` | `dataset_policy=none`; resolver raises `DatasetUnresolved` |
| F3 | `AttributeError: module 'gymnasium' has no attribute 'Tuple'` at `envs/wrappers.py:11` | only at training time, after install | no — it crashed | `RUNTIME_ERROR` | caught by the import rung in seconds |
| F4 | Repair rewrote `train.py` three times; the culprit was `envs/wrappers.py`; attempt 2 invented `from gymnasium import Tuple` | no | no — but three API calls bought nothing | `REPAIR_SAME_ERROR` | culprit localisation from the traceback + fingerprint escalation |
| F5 | Exhausted API credit produced seven files whose contents were the error message; the pipeline continued | no | yes — "generated" files that were prose | `RESOURCE_EXHAUSTION` | `GENERATION_BLOCKED_RESOURCE`, no artifact written |
| F6 | `candidate_pool.json` ended one bracket short, twice in two attempts | not until load | yes, if loaded loosely | `TRUNCATED_OUTPUT` | per-candidate generation, validated on arrival |
| F7 | Generated config ran `random_curation` and measured `selection_rate`; the protocol said `benign_curation` and `target_selection_rate` | no | yes — a different experiment, reported as this one | `UNDECLARED_CONDITION` `METRIC_SUBSTITUTION` | config written from the protocol; conformance compares them anyway |
| F8 | Model-written driver discarded the curation it had just made and built trial records from undefined names — and compiled | compile and import passed; the output contract caught it | yes, had outputs been optional | `GROUND_TRUTH_VIOLATION` `INTERFACE_ERROR` | the driver is trusted code |
| F9 | A rehearsal's trials were indistinguishable from real ones (same ids, no marker), and `preflight_leftovers` had nothing to look for | no — found by a test assertion | yes, if the files were ever combined | `GROUND_TRUTH_VIOLATION` | trials carry `smoke`; rehearsal ids are prefixed |
| F10 | `prompts.json` arrived without the `{catalogue}` placeholder the apparatus formats in | yes, on arrival | no | `MALFORMED_GENERATION` | bounded retry quoting the exact error; 4/4 recovered in pilots |

## What is still only a story

F1, F2, F4 and F5 are documented from the incident, not from a benchmark run at
B0. The commit is preserved (`ea0d7a9`), so a rate can be measured later. Until
then they support a mechanism claim, not a number.
