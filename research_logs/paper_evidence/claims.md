# Paper evidence ledger

Every claim the paper might make, what it would take to support it, and what
actually supports it today. A claim becomes paper-ready when its predefined
evidence requirements are met — not when a favourable run appears.

Paper: **Protocol before code: preventing silent scientific objective drift in
autonomous research agents.**

Last updated: 2026-09-22 (after PILOT 1 and PILOT 2).

---

## C1 — Free-form generation silently substitutes the experiment

**Claim.** An autonomous research pipeline that decides the implementation
before stating the design will, on a real brief, produce an executable
experiment that tests a different hypothesis — and report success.

**Status.** SUPPORTED BY CASE EVIDENCE, NOT YET QUANTIFIED.

**Evidence required.** The benchmark run at B0 for n ≥ 20 briefs, with the
Silent Scientific Failure Rate reported; at least one case traced end to end
from brief to wrong result.

**Supporting.** The originating incident: a choice-set curation study built as
a MiniGrid reinforcement-learning experiment against AG News, both substitutions
recorded as critical degradations while generation continued; the pre-execution
check passed it; it failed later on `gymnasium.Tuple`, and the repair loop
rewrote `train.py` three times while `envs/wrappers.py` stayed broken. Preserved
as `failure_corpus/F1-…` through `F4-…` and as benchmark positive cases PF-1,
PF-2, PF-8.

**Contradicting.** None.

**Controls completed.** None. This is a single incident, not a rate.

**Remaining threats.** One brief, one session, one model. No B0 benchmark run
exists yet; the commit (`ea0d7a9`) is preserved so one can be made.

**Ready for paper?** NO — the mechanism is documented, the rate is not.

---

## C2 — Constraining generation to content, with a trusted apparatus, makes valid completion reliable

**Claim.** When every scientific mechanism is trusted code and the model writes
only study content, a small local model produces studies that pass scientific
conformance and execute.

**Status.** PILOT EVIDENCE ONLY.

**Evidence required.** n ≥ 20 independent generations per condition on
benchmark ≥ v1, at two execution tiers (DECLARATIVE vs OPEN_ENDED) on the same
case, with valid completion and SSFR for each; at least two study families.

**Supporting.** PILOT 1 + PILOT 2 (n=10, llama3.1:8b, benchmark_v1 CL-1):
verified-ready 10/10, valid completion 10/10, silent scientific failure 0/10,
first-pass generation 6/10, bounded retry recovered 4/4, 10 distinct pool
fingerprints.

**Contradicting.** None — but the comparison against B2 is 5 attempts against
1, and B2 → B3 changed four things at once.

**Controls completed.** None. There is no OPEN_ENDED arm of the same case at
B3, which is the ablation this claim needs.

**Remaining threats.** Mock-provider execution; unseeded model sampling; one
case; one model; conformance and generation written by the same author.

**Ready for paper?** NO — needs the tier ablation and n ≥ 20.

---

## C3 — The gates detect scientific substitution rather than merely software failure

**Claim.** Scientific conformance, as a gate separate from software QA, catches
objective drift that compiles, imports, runs and produces a plausible summary.

**Status.** NOT YET TESTED AT B3.

**Evidence required.** Every benchmark_v1 positive failure case injected into
otherwise-valid B3 artifacts, one at a time, with the layer that caught each
recorded, and a false-block rate measured on the known valid variants.

**Supporting.** Mechanism exists and is unit-tested (`verify`, `verify_results`,
11 + 6 rules). PF-3 and PF-6 were observed *before* the gate existed and are
now structurally prevented rather than detected, which is a different claim.

**Contradicting.** None.

**Controls completed.** None.

**Remaining threats.** A gate that has never seen a violation in situ has an
unknown detection rate; ten clean runs say nothing about it.

**Ready for paper?** NO — this is the next experiment.

---

## C4 — Safe halting is preferable to completion, and its cost is measurable

**Claim.** The system halts rather than produce an unverifiable study, and the
false-block rate this costs is small enough to be acceptable.

**Status.** HALTING DEMONSTRATED IN DEVELOPMENT, RATE NOT MEASURED.

**Evidence required.** Safe-halt rate on resource exhaustion and on malformed
generation; false-block rate on benchmark valid variants (VV-1, VV-2) for
n ≥ 20.

**Supporting.** `GENERATION_BLOCKED_RESOURCE` observed in development when the
API key was exhausted (no artifact written, exit stated the reason) —
`failure_corpus/F5-…`. PILOT 1/2: false block 0/10 on the canonical case.

**Contradicting.** None.

**Controls completed.** No valid-variant arm has been run.

**Remaining threats.** 0/10 false blocks on the case the protocol builder was
written for is weak evidence; the variants are the test.

**Ready for paper?** NO.

---

## C5 — Per-artifact structured generation with bounded retry beats one-shot file generation for small models

**Claim.** Asking a small model for many small validated objects, rather than
one long file, converts a systematic failure into a recoverable one.

**Status.** PILOT EVIDENCE, STRONG MECHANISM.

**Evidence required.** Same case, same model, both generation strategies, n ≥ 20
each, reporting first-pass validity, retry recovery and truncation rate.

**Supporting.** One-shot: the pool ended one bracket short twice out of two
attempts at B2 (`failure_corpus/F6-…`). Per-candidate at B3: 6/10 first-pass,
4/4 retries recovered, 0/10 truncations.

**Contradicting.** None.

**Controls completed.** The two strategies were run at different commits with
different prompts, so this is not yet a controlled comparison.

**Remaining threats.** The one-shot arm has n=2. A fair comparison needs both
arms at the same commit behind a flag.

**Ready for paper?** NO — needs the paired comparison.

---

## Claims deliberately kept separate (future work, not this paper)

- **S1** choice-set capture as an oversight phenomenon in its own right
- **S2** prompt-order blinding
- **S3** provenance and legibility of a completed study
- **S4** verifier independence (who checks the checker)
- **S5** repair-policy learning from the repair telemetry
