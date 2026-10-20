# Research record

This directory is the evidence trail. From 2026-09-22 onwards, a change to this
system is not finished when its tests pass — it is finished when its effect has
been measured against a baseline and written down here.

The research direction it serves:

> **Protocol before code: preventing silent scientific objective drift in
> autonomous research agents.**

The failure that matters is not a crash. It is a run that executes, produces
numbers, looks successful, and no longer tests the hypothesis that was
approved. A crash costs an afternoon; a silent substitution costs whatever is
built on top of it.

## What lives where

| Path | What it holds |
|---|---|
| `runs/` | one Markdown record per meaningful run, never overwritten |
| `records/` | the same run as machine-readable JSON (schema v1) |
| `runs.jsonl` | one compact line per run, for aggregation |
| `summaries/` | synthesis across runs, written every 5–10 runs or at a milestone |
| `benchmark/` | versioned benchmark cases; old versions are never edited |
| `paper_evidence/claims.md` | every intended claim, its evidence, and whether it is ready |
| `baselines.md` | which commit each baseline is, and what it contained |
| `taxonomy.md` | the controlled failure labels |
| `failure_corpus/` | real failures kept as regression cases, including fixed ones |

## The workflow for every meaningful change

1. State the hypothesis: why should this help, and which failure mode does it
   target?
2. Classify it: **A** directly tests the paper hypothesis, **B** enables a
   valid test of it, **C** general reliability, **D** unrelated. Prioritise A
   and B.
3. Run the layers the change actually affects (see below).
4. Collect quantitative results with numerator and denominator — never a
   percentage alone.
5. Collect qualitative evidence: what the outputs looked like, what surprised.
6. Compare against the named baseline run or commit.
7. Write the run record (`tools/research_log.py` does the filing).
8. Update the claims ledger.
9. State what remains unproven.

## Test layers, kept separate

| Layer | What it is | Cost |
|---|---|---|
| 1 | deterministic software regression (unit, schema, compile, imports, contracts) | seconds |
| 2 | scientific invariants (protocol validity, intent fidelity, methodology gate, freeze/hash, manifest consistency, conformance) | seconds |
| 3 | controlled generated-artifact benchmark — real model output against fixed briefs | minutes |
| 4 | robustness repetitions — the same generation N times, successes/attempts | minutes |
| 5 | provider canary — minimal live call, integration only, no scientific claim | one call |
| 6 | full scientific experiment | hours |

Results from different layers are never mixed, and a fixture result is never
reported as evidence about model generation.

## Labels for the kind of evaluation

- **DEVELOPMENT** — debugging the system. Not evidence.
- **PILOT** — estimating behaviour, choosing the final design. Labelled as such.
- **CONFIRMATORY** — run only after benchmark, protocol, metrics, repetition
  count, exclusions and analysis plan are all frozen.

A confirmatory evaluation whose benchmark was changed after seeing results is
not confirmatory any more, and the record says so.

## Rules that are not negotiable

- Failed runs are recorded. Every one.
- The benchmark is versioned, never edited in place.
- A metric change after seeing results is documented as post-hoc.
- Mock-provider results are never presented as a scientific effect.
- Aggregates must be recomputable from the raw records; a summary is never the
  only evidence.
- One favourable run is not a claim.
