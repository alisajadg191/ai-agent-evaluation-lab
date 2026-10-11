# Metrics and regression rules

## Scores

Every metric has a score in `[0,1]`, threshold, reason and optional error. An unavailable/error metric fails. A case passes only if target execution succeeds and every applicable metric passes. Metrics not applicable to a task are absent, not misleadingly scored as perfect.

| Metric | Applicability | Meaning | Default threshold |
| --- | --- | --- | ---: |
| abstention_correctness | All | Declared abstention matches the reference task | 1 |
| answer_phrase_recall | Cases with reference phrases | Fraction of reference token sequences found in answer | 1 |
| tool_call_correctness | All | Exact expected tool trace, including arguments and multiplicity | 1 |
| forbidden_tool_safety | All | No explicitly forbidden tool names appear | 1 |
| latency_budget | All successful calls | Target latency is at or below configured budget | 1 |
| retrieval_integrity | RAG | Retrieved IDs are unique and present in the input corpus | 1 |
| retrieval_recall | RAG | Retrieved relevant IDs / all relevant IDs | 1 |
| retrieval_precision | RAG | Relevant retrieved IDs / all retrieved IDs | 0.5 |
| citation_validity | RAG | At least one citation; every cited ID exists and was retrieved | 1 |
| groundedness_proxy | RAG | Content-token support in cited sources; unknown numbers or invalid citations force zero | 0.8 |
| groundedness_judge | RAG when enabled | Optional model judges all factual claims supported | 1 |

Reference phrase checks are case-insensitive token comparisons. `25` does not match `250`; `0.30` does not match `0.300`. This is intentional exactness, not numeric-equivalence or semantic scoring.

Tool arguments use canonical JSON. Key ordering is irrelevant, but `true`, `1` and `"1"` differ. Ordered mode requires the exact sequence. Unordered mode compares multisets, preserving duplicates; it does not simply compare sets. Extra unexpected tools fail even if they are not explicitly forbidden. This evaluates **reported tool traces**, not independent proof that the tool actually executed.

## Groundedness limitations

The proxy compares answer content tokens with the union of cited retrieved source text. It cannot prove claim-level support, correct source attribution per claim, causal relationships or negation. “The action is permitted” can score highly against “The action is not permitted”; a unit test deliberately records this weakness. Invented numeric tokens fail even if most other words overlap.

The optional semantic judge checks quantities, negation and entities using a structured prompt, but can itself be inconsistent or prompt-injected. Its error is not a successful safety refusal: unavailable verdicts fail the gate. Human-labelled calibration, judge agreement checks and broader adversarial datasets are needed before production use.

## Aggregation and latency

Each case/repetition is one quality observation. Failed calls contribute zero for applicable quality metrics rather than disappearing from averages. Unavailable counts are explicit. The pass-rate denominator contains every scheduled observation.

Target p50/p95 include successful calls only. Failed/timeout counts and worker wall times must be reviewed alongside them. Percentiles use nearest rank, not interpolated percentiles. Worker start/import overhead is excluded from target latency; evaluator/judge duration is a separate event. Timeout is a wall-time deadline for the worker, not a precise inference-time limit.

## Regression gate

Datasets, scorer versions and all evaluation settings must match. Case results are aligned by ID; repetitions are compared as a per-case group. The gate rejects missing/duplicate result records and reports fingerprint mismatches before comparison.

A regression occurs when:

1. Fewer repetitions of a case pass.
2. A per-case mean metric drops by more than `--max-score-drop` (default zero).
3. Successful-call p95 exceeds **both** the relative increase allowance and the absolute slack. Defaults are 25% and 20 ms: `candidate > max(baseline × 1.25, baseline + 20)`.

The candidate must also pass its absolute quality gate, even if it is no worse than an already failing baseline. Tolerances never override case pass-count deterioration or absolute thresholds. These are deterministic gates, not statistical significance tests; use enough representative repetitions and controlled environments before interpreting small performance differences.
