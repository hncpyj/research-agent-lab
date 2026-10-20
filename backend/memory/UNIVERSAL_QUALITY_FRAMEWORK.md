# Universal Quality Framework
## Evaluating Any Knowledge Work Output — Code, Research, Business, Content

> *"The same five questions expose weaknesses in a research paper,
> a business proposal, a marketing campaign, and a codebase.
> The domain changes. The failure modes don't."*

---

## The Core Insight

After simulating expert peer review on AI-generated research, a pattern emerged:
the evaluation criteria aren't research-specific. They're **universal properties
of any knowledge work** that claims to solve a problem.

The five universal failure modes:
1. **Misalignment** — solves the wrong problem
2. **Insufficient evidence** — claims without support
3. **Missing coverage** — experts immediately see the gaps
4. **Domain standard violations** — unaware of how the field works
5. **Wrong audience** — built for who you imagine, not who actually judges it

---

## The Five Evaluation Dimensions

### 1. ALIGNMENT
*"Does this output actually address the real problem?"*

This is the most common and most costly failure. The output is well-executed,
but it solves a different problem than the one that matters.

**Questions:**
- What problem does this claim to solve?
- Does the implementation actually test/demonstrate that claim?
- Is the success metric aligned with the actual goal?

**The Alignment Test:**
> State the original intent in one sentence.
> State what the output actually does in one sentence.
> Are they the same?

**Examples across domains:**

| Domain | Alignment Failure |
|--------|------------------|
| Research | RL experiment code in a retrieval paper — measures the wrong thing |
| Product | Built the feature users requested, not the one they needed |
| Marketing | Brand awareness campaign when the problem is conversion |
| Code | Optimized the wrong bottleneck — fast code that runs rarely |
| Business proposal | Detailed execution plan when investor wants market validation |

**Fix:** Always start with the success metric, then check if the output moves that metric.

---

### 2. EVIDENCE
*"Are claims backed by sufficient, appropriate data?"*

Outputs make claims. Claims require evidence. The right amount and type of evidence
depends on who's judging.

**Questions:**
- What is the central claim?
- What evidence supports it?
- Is the sample size / data sufficient?
- Could someone else replicate this result?

**The Evidence Ladder:**

```
Anecdote          (weakest) → "I think this works"
Single case                 → "It worked once"
Small sample                → "It worked in 3 cases"
Statistical sample          → "n=500, mean±std"
Significance tested         → "p<0.05, 95% CI"
Replicated externally       → "3 independent studies confirm"  (strongest)
```

Most AI-generated work lives at the top two rungs. Top venues require the bottom three.

**Minimum thresholds by domain:**

| Domain | Minimum Evidence Standard |
|--------|--------------------------|
| ML Research | 3+ seeds, confidence intervals, significance tests, 1K+ test samples |
| A/B Testing | n≥1000 per variant, p<0.05, primary metric pre-registered |
| Business Case | 3+ comparable companies, TAM from multiple sources, unit economics |
| Code Quality | Test coverage ≥70%, integration tests, performance benchmarks |
| UX Research | 5+ user interviews, task completion rate, quantitative validation |

---

### 3. COVERAGE
*"What would an expert immediately notice is missing?"*

This is the fastest way to be dismissed by a domain expert.
Coverage failures signal "the author doesn't know the field."

**The Coverage Test:**
Name the 3 kinds of expert reviewer who evaluate this type of work (by specialty, not by person).
What would each of them look for first?

**Research example (Information Retrieval):**
> An IR-systems reviewer looks for: BM25 baseline, BEIR evaluation, sufficient test queries
> A dense-retrieval reviewer looks for: DPR citation, hard negative mining, random baseline
> A practical-retrieval reviewer looks for: SBERT citation, MTEB evaluation, cross-domain generalization

**Template for any domain:**

```
Domain Expert Persona: [Name a real expert]
Their first question: [what they check immediately]
Their red line: [what causes instant dismissal]
Their standard: [the benchmark/format they expect]
```

**Common coverage gaps by domain:**

| Domain | Universal Coverage Requirements |
|--------|---------------------------------|
| Research papers | Related work, ablations, baselines, limitations section |
| Software projects | README, tests, error handling, performance benchmarks |
| Business plans | Competition analysis, risk/mitigation, go-to-market, financials |
| Marketing content | CTA, mobile optimization, A/B variant, tracking setup |
| Product specs | Edge cases, failure modes, rollback plan, success metrics |

---

### 4. DOMAIN FIT
*"Does this meet the unwritten standards of this field?"*

Every domain has conventions that aren't explicitly stated anywhere
but that practitioners instantly recognize. Violating them signals outsider status.

**How to identify domain standards:**
- Find 3 high-quality examples of the output type
- List what they all have in common
- List what the top 1% have that the top 10% don't

**Domain standard checklists:**

*Academic Research:*
- [ ] 30+ references (conference), 50+ (journal)
- [ ] Statistical significance with effect size
- [ ] Reproducibility: code + data available
- [ ] Limitations section is honest, not brief
- [ ] Prior work cited within last 2 years

*Software (Production):*
- [ ] Input validation on all external data
- [ ] Graceful degradation on dependency failure
- [ ] Logs at the right level (not too much, not too little)
- [ ] Configuration externalized (no hardcoded values)
- [ ] Observability (metrics, traces, alerts)

*Investor Pitch Deck:*
- [ ] Problem → Solution → Market → Business model → Traction → Team → Ask
- [ ] TAM/SAM/SOM clearly differentiated
- [ ] Unit economics (CAC, LTV, payback)
- [ ] Why now? (market timing)
- [ ] Why you? (unfair advantage)

*Business-to-Business Proposal:*
- [ ] Executive summary fits on one page
- [ ] ROI calculation with conservative/base/optimistic scenarios
- [ ] Implementation timeline with milestones
- [ ] Risk matrix with mitigations
- [ ] Clear next step and decision deadline

---

### 5. AUDIENCE MATCH
*"Is this built for who actually judges it, or who you imagine judges it?"*

The same content needs different framing for different audiences.
AI systems and junior practitioners both default to the "average reader."
Expert evaluators are not average readers.

**The Audience Map:**

```
Who reads it first?  → Gatekeeper (must pass, doesn't decide)
Who decides?         → Decision maker (cares about impact + risk)
Who advises them?    → Domain expert (cares about rigor + precedent)
Who implements it?   → Practitioner (cares about clarity + completeness)
```

Optimize for the decision maker. Satisfy the domain expert. Don't lose the gatekeeper.

**Audience adjustment examples:**

| Content | For Gatekeeper | For Decision Maker | For Domain Expert |
|---------|---------------|-------------------|------------------|
| Research | Abstract clarity | Key result + impact | Methodology rigor |
| Code PR | CI passes | Business impact | Code quality patterns |
| Business proposal | Legal/format compliance | ROI + risk | Technical feasibility |

---

## The Reviewer Persona Method

The most effective way to apply this framework:
**Name the 3 people in the world most likely to evaluate your output.**
Ask what each would check first, what would cause them to stop reading,
and what would make them champion it.

This works because:
- Abstract criteria are easy to satisfy superficially
- Named experts have known red lines that are harder to fake
- It forces you to think about the actual evaluation context, not the ideal one

**Template:**

```markdown
## Reviewer Simulation: [Output Type]

### Reviewer 1: [Name] ([Institution/Role])
- First check: ___
- Red line: ___
- What would impress them: ___
- Verdict on current output: ___

### Reviewer 2: [Name] ([Institution/Role])
...

### Consensus gaps:
- [ ] Gap 1
- [ ] Gap 2
- [ ] Gap 3
```

---

## Quick Evaluation Protocol

Use this in under 10 minutes for any output:

```
1. ALIGNMENT (2 min)
   → State the problem being solved in one sentence.
   → State what the output actually does in one sentence.
   → Match? If not, stop — fix alignment first.

2. EVIDENCE (2 min)
   → List the main claims.
   → For each: what's the evidence? Is it sufficient for the target audience?
   → Any claim without evidence = either add evidence or remove claim.

3. COVERAGE (2 min)
   → Name one expert who would evaluate this.
   → What are the first 3 things they look for?
   → Are all 3 present?

4. DOMAIN FIT (2 min)
   → Compare against 2-3 high-quality examples in the same category.
   → What do they have that this doesn't?

5. AUDIENCE (2 min)
   → Who actually decides if this succeeds?
   → Is the output framed for them specifically?
```

---

## Applying to AI-Generated Work

AI outputs consistently fail in predictable ways:

| AI Failure Pattern | Which Dimension | Fix |
|-------------------|-----------------|-----|
| Generated RL code for retrieval research | Alignment | Domain-aware system prompts |
| 8 references in a research paper | Coverage | Minimum reference count check |
| 512 test samples | Evidence | Minimum dataset size validation |
| No baseline comparison | Coverage | Required baselines by domain |
| Template report instead of LLM analysis | Alignment | Fallback chain (API → local → template) |
| Perfect syntax, wrong architecture | Domain Fit | Expert persona review before code gen |

**Rule:** Run this framework *before* finalizing AI output, not after.
Prevention is 10× cheaper than correction.

---

## Cross-Domain Quality Equivalences

These are "the same check" across different fields:

| Concept | Research | Code | Business | Content |
|---------|----------|------|----------|---------|
| Baseline | BM25 comparison | Performance benchmark | Competitor analysis | Control variant |
| Test set | BEIR evaluation | Integration tests | Pilot customers | A/B test |
| Significance | p-value, CI | Benchmark repeatability | Statistical validation | Confidence interval |
| Reproducibility | Code + data repo | README + Docker | Process documentation | Playbook |
| Peer review | Conference review | Code review + PR | Board/advisor review | Expert critique |
| Ablation | Remove components | Feature flags | Pilot scope reduction | Variant testing |
