# General Peer-Review Guide

This document defines a general, evidence-based process for reviewing research
manuscripts. It contains no material from any specific submission, author,
review, rebuttal, or confidential venue discussion.

## 1. Confidentiality and conflicts

- Treat every non-public manuscript and all supplementary material as confidential.
- Do not copy submission text, unpublished results, reviewer discussions, or author
  identities into public repositories, shared prompts, or unrelated systems.
- Do not attempt to identify anonymous authors.
- Disclose conflicts of interest and stop reviewing when impartiality is uncertain.
- Use external tools only when their data-handling terms are compatible with the
  applicable review policy.
- Delete temporary local copies when they are no longer required.

## 2. Review principles

A strong review is specific about the manuscript's claims but conservative about
what can be inferred. It should:

- evaluate the work actually presented;
- distinguish factual errors from missing evidence and presentation issues;
- connect each criticism to a claim, method, experiment, or documented omission;
- explain why an issue matters to the paper's conclusions;
- request the smallest additional evidence needed to resolve uncertainty;
- acknowledge strengths and credible negative results;
- avoid speculation about author intent, identity, or competence.

## 3. Evidence map

Before assigning an overall assessment, construct a compact evidence map:

| Item | Question |
| --- | --- |
| Main claim | What is the paper asking the reader to believe? |
| Supporting evidence | Which analyses or experiments support that claim? |
| Assumptions | What must hold for the evidence to be valid? |
| Alternatives | Which competing explanations remain plausible? |
| Scope | Where does the claim apply, and where does it not apply? |
| Reproducibility | Is there enough information to check or reproduce the result? |

Do not infer missing evidence from confident language. Record an unsupported claim
as unsupported, not as false, unless the manuscript provides contradictory evidence.

## 4. Methodological checks

### 4.1 Problem formulation

- Is the research question stated clearly?
- Are the target population, task, and unit of analysis defined?
- Are the hypotheses or objectives distinguishable from exploratory analyses?
- Does the operationalization measure the concept named in the claim?

### 4.2 Study design

- Does the design permit the stated causal, predictive, or descriptive conclusion?
- Are comparison groups and interventions defined consistently?
- Could selection, leakage, confounding, or post-treatment adjustment explain the result?
- Are exclusions, stopping rules, and repeated analyses documented?

### 4.3 Data and measurement

- Is the data source appropriate for the claimed scope?
- Are sampling, filtering, annotation, and preprocessing procedures described?
- Are measurement validity and reliability addressed?
- Could duplication, contamination, missingness, or label construction bias the result?

### 4.4 Evaluation

- Do the metrics correspond to the scientific question?
- Are comparisons implemented under comparable conditions?
- Are uncertainty and variability reported appropriately?
- Are ablations and sensitivity checks targeted to plausible alternative explanations?
- Are failure cases described without selecting only favorable examples?

### 4.5 Baselines and prior work

- Are relevant classes of prior approaches represented?
- Are baselines implemented and tuned fairly?
- Are improvements attributed only to components that differ between conditions?
- Does the related-work discussion accurately describe the contribution boundary?

### 4.6 Reproducibility

- Are data provenance, code versions, configurations, and randomization procedures clear?
- Are prompts, schemas, preprocessing steps, and evaluation rules available when they
  materially determine the result?
- Are compute requirements and external dependencies described at a useful level?
- Can a reader distinguish fixed design choices from decisions made after observing results?

### 4.7 Ethics and broader impact

- Are privacy, consent, licensing, and data-governance constraints addressed?
- Are foreseeable harms and misuse risks considered in proportion to the contribution?
- Are demographic or distributional limitations reported where relevant?
- Are claims about safety or societal benefit supported by direct evidence?

## 5. Severity and actionability

Classify concerns by their effect on the central conclusions:

- **Critical:** the main conclusion cannot currently be supported or the evaluation is
  invalid under a plausible interpretation.
- **Major:** substantial evidence or clarification is needed, but the core approach may
  remain viable.
- **Minor:** the issue affects clarity, completeness, or a limited secondary claim.
- **Editorial:** wording, formatting, or presentation can be corrected without changing
  the scientific interpretation.

For every critical or major concern, state:

1. the affected claim;
2. the evidence that is missing or inconsistent;
3. the consequence for interpretation;
4. a feasible way to resolve or bound the issue.

## 6. Writing the review

Use the following structure unless the venue requires a different form.

### Summary

Describe the question, approach, evidence, and claimed contribution neutrally. Do not
copy the abstract or add claims that the paper does not make.

### Strengths

Identify concrete strengths such as a well-motivated question, sound design, careful
analysis, useful artifact, clear limitation, or credible negative finding.

### Main concerns

Order concerns by consequence for the central claims. Keep independent issues separate,
cite the relevant manuscript location, and avoid multiplying complaints that arise from
one underlying problem.

### Questions

Ask questions whose answers could change the assessment or materially improve the final
paper. Avoid questions that merely test whether the authors have read unrelated work.

### Overall assessment

Explain how the strengths and unresolved concerns determine the recommendation. The
written rationale should stand on its own without relying on a numeric score.

## 7. Revision and rebuttal

When evaluating a response or revised manuscript:

- compare each original concern with the corresponding response and changed evidence;
- distinguish a promised future change from a completed correction;
- check whether narrowing one claim leaves adjacent claims overstated;
- update the assessment when evidence changes;
- do not introduce unrelated requirements merely because the authors answered earlier ones.

## 8. Responsible use of automated tools

Automated tools may help organize notes, check consistency, or improve prose, subject to
the review policy. They must not replace the reviewer's judgment or receive confidential
content when disclosure is prohibited.

Before submitting a tool-assisted review:

- verify every factual statement against the manuscript;
- remove generic filler and unsupported assertions;
- ensure the wording does not imply access to evidence that was not provided;
- confirm that no confidential text, personal data, or hidden metadata is exposed;
- take responsibility for the final recommendation and its reasoning.

## 9. Final checklist

- The summary is accurate and neutral.
- Every major concern is tied to a claim and supporting evidence.
- Severity reflects impact on conclusions rather than personal preference.
- Requested changes are necessary, feasible, and prioritized.
- Strengths are concrete rather than ceremonial.
- Limitations and uncertainty are represented fairly.
- The review contains no author-identification attempts or personal characterizations.
- The review contains no text or details copied from another confidential submission.
- The recommendation follows from the written assessment.
- The final text complies with the applicable confidentiality and tool-use policies.
