# Research Quality Rubric
> Derived from expert reviewer simulation (2026-02-24)  
> Apply at each pipeline phase to catch issues early — not just at the end.

---

## The 5 Instant-Reject Criteria (Any top venue)

| # | Criterion | Threshold | How to Check |
|---|-----------|-----------|--------------|
| R1 | **Test set size** | ≥ 1,000 queries (IR); ≥ 500 samples (ML) | Parse config for test_samples |
| R2 | **Reference count** | ≥ 25 (conference short); ≥ 40 (journal/long) | Count papers in references |
| R3 | **Baseline comparison** | At least 3 baselines, incl. non-neural | Check experiment code for baseline classes |
| R4 | **Experiment-hypothesis alignment** | Code must test what the hypothesis claims | Semantic check: imports vs. research topic |
| R5 | **Statistical significance** | CI or p-value required for main claims | Check eval code for t-test / bootstrap |

---

## The 10-Dimension Quality Rubric

| Dimension | Weight | Poor (0-3) | Acceptable (4-6) | Strong (7-10) |
|-----------|--------|-----------|-----------------|--------------|
| **Novelty** | 20% | Combines existing methods, no new insight | New combination with theoretical justification | New method or theory with proof/analysis |
| **Experimental Rigor** | 20% | <1K test, no error bars | 1-10K test, ±std reported | 10K+ test, CI, multiple seeds, ablations run |
| **Reproducibility** | 10% | No config, no seed | Config file, fixed seed | Full code + data + environment on GitHub |
| **Related Work Coverage** | 15% | <15 refs, misses key papers | 20-30 refs, covers main baselines | 40+ refs, systematic coverage |
| **Baseline Comparison** | 15% | 0-1 baselines | 2-3 baselines | 5+ baselines including SoTA |
| **Dataset Appropriateness** | 10% | Synthetic only | Public dataset but small/niche | Standard benchmark (BEIR, GLUE, ImageNet, etc.) |
| **Statistical Validity** | 5% | No statistics | Mean/std only | Paired t-test, bootstrap CI, effect size |
| **Contribution Clarity** | 5% | Unclear what is new | Contribution listed but vague | Single clear claim, proven by experiment |

---

## Domain-Specific Required Baselines

### Information Retrieval
- BM25 (mandatory sanity check)
- SBERT (paraphrase-mpnet-base-v2)
- DPR (facebook/dpr-ctx_encoder-single-nq-base)
- Standard benchmark: BEIR (18 domains), MS-MARCO, MTEB

### Computer Vision
- Supervised ResNet/ViT (ImageNet pretrained)
- SimCLR or DINO (self-supervised baseline)
- Standard benchmark: ImageNet, CIFAR, VTAB

### NLP / Text Classification
- BERT-base fine-tuned
- GPT-2 few-shot
- Standard benchmark: GLUE, SuperGLUE, BIG-Bench

### Domain Adaptation
- Source-only (no adaptation)
- DANN (Ganin et al., 2016)
- DomainBed evaluation suite

---

## The "Experiment Code Alignment" Check
**The single most common AI-generated research failure.**

| Research Topic Keywords | Forbidden Imports (wrong framework) | Required Imports |
|------------------------|-------------------------------------|------------------|
| retrieval, ranking, search | gymnasium, MiniGrid, policy_loss, value_loss | faiss, beir, sentence_transformers |
| domain adaptation | only simulated domains | real domain datasets |
| contrastive learning (NLP) | image-only augmentations | text augmentations, HuggingFace |
| classification | RL reward, episode | sklearn metrics, confusion matrix |

**Red flag strings in experiment code:**
```
MiniGrid, gymnasium.make, policy_loss, value_loss, 
episode_return, simulate_*, rollout, PPO, A2C
```

---

## Reviewer Persona Reference

Roles, not real people: earlier versions named real researchers and gave them invented quotes.

### Reviewer A — IR systems
- Red lines: no BM25 baseline, test set <1K, no BEIR evaluation

### Reviewer B — Dense retrieval
- Red lines: DPR not cited, no hard negative mining explanation, no random baseline for the transfer metric

### Reviewer C — MMD / kernel methods
- Red lines: bandwidth=constant (should be median heuristic), no theoretical justification

### Reviewer D — Practical retrieval
- Red lines: SBERT not cited, no MTEB evaluation, cross-modal mixing without justification

### Reviewer E — Domain adaptation
- Red lines: pixel augmentation ≠ semantic domain shift, no DomainBed comparison

---

## Negative Result Framing Guide
When main hypothesis FAILS (e.g., domain_gap still high after training):

**Don't:** "Our method achieved domain gap = 0.84 (failure)"
**Do:** "We empirically demonstrate that low-level synthetic augmentations are insufficient for semantic domain invariance, identifying a gap that motivates future work on X."

Target venues for honest negative results:
- EMNLP Findings track
- ECIR Short Papers  
- NeurIPS Datasets & Benchmarks track
- *ACL workshops

---

## Priority Fix Order (for any research project)

1. 🔴 **Validate experiment code matches hypothesis domain** (biggest risk)
2. 🔴 **Replace synthetic test data with real benchmark** (validity)
3. 🔴 **Add mandatory baselines** (BM25 / domain-appropriate)
4. 🟡 **Expand references to 30+** (credibility)
5. 🟡 **Run ablations, report results** (rigor)
6. 🟡 **Add statistical significance tests** (validity)
7. 🟢 **Frame negative results correctly** (publishability)
8. 🟢 **Apply IEEE/ACL/NeurIPS template** (formatting)
