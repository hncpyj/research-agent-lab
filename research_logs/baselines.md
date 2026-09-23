# Baselines

Preserved as actual commits, so each can be checked out and re-run rather than
reconstructed later. Reconstructing a deliberately weak baseline after the fact
is not evidence.

| ID | Commit | What it contained |
|---|---|---|
| **B0** | `ea0d7a9` | Free-form generation. A hypothesis was keyword-matched to a code template; an unmatched one fell back to the reinforcement-learning template, and an unmatched dataset fell back to AG News. Both were recorded as critical degradations and generation continued. No preflight. Repair rewrote the phase entry script whatever the traceback said. |
| **B1** | `034d446` | Software QA. The two silent fallbacks removed (unknown now raises); preflight ladder compile → imports → smoke; traceback-localised repair with fingerprint escalation; patch guard on fabrication and data-source changes. No scientific design layer: what the study *was* remained implicit in the template. |
| **B2** | `6cf71b8` | Typed spec. `ExperimentSpec` stated study type, conditions, outcomes and required outputs; a controlled-LLM scaffold existed; contract checks read the generated artifacts. No lifecycle, no hash, no methodology gate, and the driver was still model-generated. |
| **B3** | `4d61002` | Protocol-first. `StudyProtocol` with DRAFT → METHODOLOGY_REVIEW → APPROVED → FROZEN, version and science-only hash; methodology review as a hard gate; `BuildManifest` bound to the protocol hash; declarative execution tier for controlled_llm (apparatus and config are trusted code, the model writes only candidates and wording); scientific conformance as a gate separate from software QA; status enum that distinguishes resource exhaustion from bad output. |

## Comparability

B0 and B1 cannot be run through `study_builder` at all — it did not exist. To
compare them on a benchmark case, check out the commit and run that version's
own generation entry point. Any comparison must state which entry point was
used on each side; they are different programs, not settings of one.

B1 → B2 → B3 also changed more than one thing each. Where a run needs a clean
ablation, disable the gate under test at B3 rather than pretending an older
commit is that ablation.
