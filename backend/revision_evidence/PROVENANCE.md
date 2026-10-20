# Revision-evidence package provenance

## Scope

This package was created by read-only extraction from existing repository records. No scientific experiment, model call, label generation, gate execution, or confirmatory analysis run was performed. No frozen source record was modified. The paper was not edited. The only new artifacts are under `revision_evidence/`.

Extraction date: 2026-09-24 (Europe/London). Missing metadata is reported as `UNKNOWN`.

## Cross-file integrity checks performed during extraction

- Intent holdout: 42 generated IDs = 42 frozen label IDs = 42 result IDs; sets identical.
- Apparatus holdout: 24 generated IDs = 24 frozen label IDs = 24 result IDs; sets identical.
- Confirmatory run: 384 raw rows form 192 seeds with exactly both conditions; all 16 design-freeze artifact hashes match; raw data hash matches both recorded result artifacts.
- No numerical mismatch was silently corrected. CSV values are direct transformations of frozen rows; `pair_id` is explicitly defined as the scheduled seed.

## Output hashes

SHA-256 values below cover the eight non-provenance outputs as created. `PROVENANCE.md` omits its own hash to avoid a circular value.

| Output | SHA-256 |
|---|---|
| `revision_evidence/intent_holdout_42_cases.csv` | `a7f7bb3c21e8f593432fc8a428f879af32b6a0e5c0a2600055e97154ba49c74e` |
| `revision_evidence/intent_holdout_method.md` | `064fe5b765c24d1765be15c9bc61cf9ab565baa82aea5bdf385cf4407bddd119` |
| `revision_evidence/ambiguous_pass_case.md` | `adfe9f30f1224426bd0b2b5f8042f45bd64162967a6d5e946575b65aac096e44` |
| `revision_evidence/intent_fidelity_implementation.md` | `aea72b107110903ac12611b87efa842a5c4999f8e0d5af75495ef2305baed6a9` |
| `revision_evidence/apparatus_holdout_24_mutations.csv` | `c2324d03db8f4cd43f73448f586aa1fad87320e0c94f665734003e47af711ccf` |
| `revision_evidence/apparatus_holdout_method.md` | `9deed317cada43bab3309e116027456eda1e34bd13d171e615eb0bf18093c500` |
| `revision_evidence/choiceset_h1_pairs.csv` | `640767b8039e939f62d5da4c314fb104d83c51deb60a7027fc47a093c6f775e5` |
| `revision_evidence/bootstrap_interpretation.md` | `ade2ac5a4c60018f24da144dd149a8ef534d81bed288f1e3c3ac1809d738f66d` |

## Principal source hashes

| Source | SHA-256 |
|---|---|
| `research_logs/raw/20260922_choiceset_holdout_v6.json` | `fea4bc573db6d4028f812d25207e4fc4e0f6c73bfce52399989b5e9c75c6eb22` |
| `research_logs/raw/20260922_choiceset_labels_v6.json` | `59ce26650bb1c8507ad3dd1175571d0dd2dfefaa523da30edebafccae499a9b1` |
| `research_logs/raw/20260922_choiceset_eval_v6.jsonl` | `77ca6d97e64e73194133ea6c60a20d8663a864de5d64d1e6a02afa762e620d5c` |
| `research_logs/raw/20260922_choiceset_totals_v6.json` | `04594e0d71b78112f9364078386f74f83ec0496dc57a88c3fdd436309a999323` |
| `research_logs/raw/20260922_evidence_freeze_v6.json` | `32efb9e1db45a7449799ac5efd7f1b3a64d98944b355a01d5e831b193b8bfcd5` |
| `research_logs/runs/20260922_1932_choiceset_holdout_v6.md` | `dae6dc4fc5fd71a10e2de9970287c394f5abc4417545b1851b11bcd845ca45ac` |
| `agents/intent_fidelity.py` | `36142244517f043bed42b40ee1e58a6f2a2a77ed434a4bc964ac56e8c8880fd6` |
| `agents/scientific_concepts.py` | `d275e58c3bc3e1480ebd58b15739131bbd13dd261d0f36ffcf67a989ac318e6f` |
| `tools/fidelity_benchmark.py` | `626e10c5b5c2b03d7d019026bf0cd93591adaf97425a442aa9498bc092488b14` |
| `research_logs/raw/20260922_apparatus_holdout_v4.json` | `c1698a49117d0fd053fd505ecd0b3dd5005cb1465c44cc66b33bec7563ddb0e7` |
| `research_logs/raw/20260922_apparatus_labels_v4.json` | `17d2970d4f8f997f2b8a5afbc4521686a95091ecee25f809a7b9f018fc9c3a0e` |
| `research_logs/raw/20260922_apparatus_eval_v4.jsonl` | `52216d0d069b4c91b1f3986192ee9d9a1f763222b41c8a0dd57317a1486b0065` |
| `research_logs/raw/20260922_apparatus_totals_v4.json` | `b313f56bddc4d7c848f5fdc373d71d606f2605e2e58980bcaee4d2af17c936c9` |
| `research_logs/raw/20260922_hardening_freeze_v4.json` | `6293127f4898bb999203e471d73479e40b20061cb5ae9540d4748b3c35cb85f7` |
| `research_logs/runs/20260922_1501_apparatus_holdout.md` | `df6f78ce24b97cd4f77e3a78ad202b724199fc2a8e49ec670227fce0aa0caa0b` |
| `confirmatory_runs/choiceset_h1_confirmatory_v1/confirmatory_design_freeze.json` | `de9cb216f160d7c552bb50e96aefe07435b21dbfaef90628ed68e21430e5ed30` |
| `confirmatory_runs/choiceset_h1_confirmatory_v1/confirmatory_schedule.json` | `7174bc6b46cc87b7913fc859f0130f8feff9b975d9339eb9aee2ea38bcc1e278` |
| `confirmatory_runs/choiceset_h1_confirmatory_v1/confirmatory_analysis.py` | `ad2c01e039bf44f209a0fc5b6ddc7c8a299a723e89e26c0286cea52c7668d0df` |
| `confirmatory_runs/choiceset_h1_confirmatory_v1/results/raw_trials.jsonl` | `d615ceb4d4894866c6f99eb5aba09de1918ab7659503a84c4028462ac014218f` |
| `confirmatory_runs/choiceset_h1_confirmatory_v1/results/confirmatory_analysis.json` | `3c4a47abd1dff1e70afb0461db7c661683874d233f3c8a4d6dd5bea3e945c428` |
| `research_logs/raw/20260923_0022_choiceset_confirmatory_result.json` | `f19046fb5a8e9cce54fdba0025d35274271853bab6592b5a23893c6604694b52` |
| `research_logs/runs/20260923_0022_choiceset_confirmatory_result.md` | `20e916701905dac8bd88d42b40fbb185cde8a7f310b4bcffb39b75d8ca7d3b41` |

The manuscript inspected for the discrepancy report was an external working draft. It was read but not modified; its machine-local path is intentionally omitted from this public package.

## Discrepancy report

### Claims in the current paper that are fully supported

- The complete 42-case counts and outcome matrix: 18 drifted (0 PASS / 14 FAIL / 4 NEEDS_HUMAN), 16 faithful (9 / 1 / 6), 8 ambiguous (1 / 2 / 5), 28/42 exact pre-specified verdict agreement, and 15/42 total escalations.
- The 42 cases were a fresh in-domain set generated without checker/repository access, hand-labelled before evaluation, and all generated IDs were retained. The gate itself was deterministic; `claude-opus-5` generated cases rather than verdicts.
- The apparatus set comprised 18 behavior-changing and 6 behavior-preserving edits; 18/18 changing edits were stopped with integrity enabled, 15/18 were accepted by the remaining stack with integrity disabled, exactly three were stopped elsewhere (M04 and M10 by Result Conformance; M07 by Software Preflight), and 6/6 preserving edits were refused.
- “Generator-blind, manually labelled” and “no independent adjudication is recorded” accurately describe the apparatus evidence.
- The Choice-Set frozen run used 192 paired seeds / 384 records; benign target selection was 25/192, adversarial 52/192, difference +14.0625 pp, paired percentile interval [+8.3333, +20.3125] pp, and approval was 192/192 in both conditions.
- The bootstrap used 100,000 paired-unit resamples, primary seed 20260923, and the frozen lower-bound decision rules. The design, schedule, raw-data, and analysis hashes currently verify.

### Claims that need wording tightened

- “Ambiguous identity mappings are escalated rather than silently certified” is supported only as a rule-level description of non-blocking identity findings when no blocking mismatch co-occurs. It must not be generalized to all ambiguity: the frozen ambiguous subset produced 5 NEEDS_HUMAN, 2 FAIL, and 1 PASS.
- Any explanation of D18 should distinguish the frozen evaluation failure from its exact parser mechanism. The run report attributes PASS to unstated causality not being escalated, while static inspection of the same hash-identified source can recognize “leads to” in the hypothesis as causal; the frozen row lacks the intermediate parse needed to resolve this explanatory discrepancy.
- “95% CI” should be described as the predeclared paired-unit percentile-bootstrap interval for the fixed counterbalanced schedule unless a sampling population and repeated-sampling target are added. Coverage beyond the recorded schedule is not defined.
- Apparatus non-redundancy is supported for the tested source-mutation family and this exact content-integrity control, not for every safeguard or non-source mutation route. The paper mostly states this boundary already.

### Information absent from the repository

- Individual intent-label author identity, independent label adjudication, full generation prompt, generator model version, decoding settings, and generation seed.
- Individual apparatus-label author identity, independent adjudication, full mutation-generation prompt/settings/seed, and a retained standalone source path for the 24-case replay driver.
- The intermediate parsed causality value for D18, which prevents resolving the discrepancy between the run narrative and static source inspection.
- An explicit superpopulation or repeated-sampling interpretation for the paired bootstrap.
- A clean Git commit that alone reconstructs the frozen intent-fidelity implementation; the run was recorded on a dirty working tree, so component hashes are the operative identity.

### Any numerical mismatch

- **None found.**
