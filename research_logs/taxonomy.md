# Failure taxonomy (v1)

One controlled vocabulary, so counts can be compared across runs. A failure may
carry more than one label. A new label is added only when an existing one would
hide a distinction that matters — and the reason is recorded here.

## Scientific failures — the ones the research direction is about

| Label | Means |
|---|---|
| `INTENT_DRIFT` | the protocol no longer expresses the approved question |
| `PROTOCOL_ERROR` | the protocol is internally invalid or incomplete |
| `METHODOLOGY_ERROR` | the design cannot support the claim it makes |
| `WRONG_EXPERIMENT_FAMILY` | a different kind of study was built |
| `UNDECLARED_CONDITION` | a condition appears or disappears without the protocol |
| `METRIC_SUBSTITUTION` | something other than the declared outcome is measured |
| `DATASET_SUBSTITUTION` | data the protocol never named |
| `GROUND_TRUTH_VIOLATION` | the frozen ground truth was altered or bypassed |
| `CANDIDATE_MUTATION` | a candidate's content changed after freezing |
| `MANIPULATION_LEAKAGE` | the condition is detectable by the agent being measured |
| `CONFOUND` | an uncontrolled alternative explanation |

## Generation failures

| Label | Means |
|---|---|
| `MALFORMED_GENERATION` | output does not satisfy its schema |
| `TRUNCATED_OUTPUT` | output stopped mid-structure |

## Software failures

| Label | Means |
|---|---|
| `DEPENDENCY_ERROR` | a required package is absent or incompatible |
| `IMPORT_ERROR` | a module does not import |
| `INTERFACE_ERROR` | a contract between components is broken |
| `RUNTIME_ERROR` | the run raised at execution time |

## Repair failures

| Label | Means |
|---|---|
| `REPAIR_SAME_ERROR` | the patch left the identical failure |
| `REPAIR_REGRESSION` | the patch introduced a new failure |

## Outcomes that are not defects

| Label | Means |
|---|---|
| `RESOURCE_EXHAUSTION` | no provider or model was available |
| `SAFE_HALT` | the system stopped rather than produce an unverifiable result |
| `FALSE_BLOCK` | a valid study was blocked — a real cost of the gates |
| `UNKNOWN` | not yet diagnosed; must not stay unknown in a synthesis |

`SAFE_HALT` is the intended behaviour when correctness cannot be established.
`FALSE_BLOCK` is its price, and both are counted so the trade-off is visible.
