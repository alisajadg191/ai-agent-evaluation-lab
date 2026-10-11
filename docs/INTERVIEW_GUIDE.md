# Interview walkthrough

## Explain the project in one minute

“I built an evaluation lab that separates application inputs from expected results, executes a target under a deadline, scores RAG and tool behaviour, and writes reproducible reports. It checks citations, retrieval, reference phrases, exact tool arguments and forbidden calls. A regression gate compares per-case outcomes and latency under matching dataset/configuration fingerprints. LangSmith publication is optional and uses recorded measurements, while the local path runs without paid models.”

## Five-minute demonstration

1. Open the dataset and point out that `inputs` and `reference` are separate.
2. Run the good target and show the HTML report and citations.
3. Run the flawed target; explain its invented source, wrong tool arguments and forbidden calls.
4. Compare the reports and show the nonzero regression exit code.
5. Show a timeout or malformed response test, then explain the groundedness proxy's negation limitation.

## Questions and answers

**How is evaluation different from observability?** Evaluation applies explicit quality criteria to outputs. Observability records what ran, timings, errors and context. This project has local events and optional LangSmith experiments, alongside quality scores.

**Why keep references out of the target?** Passing expected outputs to the application would leak answers and inflate its score. The worker receives only the `Inputs` contract; the evaluator retains reference data separately.

**How do you test tool correctness?** Compare the structured trace, including names, typed argument values, ordering and duplicates. Do not trust a natural-language statement saying a tool was used.

**Is lexical groundedness enough?** No. Token overlap misses negation and other meaning changes. The project names it a proxy, documents a false-positive example and supports an optional semantic judge. Judges need calibration too.

**Why can't aggregate pass rate be the only regression metric?** Improvements in one case can conceal degradation in another. This lab compares case-level pass counts and metric means before considering the overall absolute gate.

**What does p95 mean?** Sort successful target runtimes and take the nearest-rank 95th percentile. It does not include failed calls, so failure/timeout counts must be reviewed alongside it. With few samples it is an unstable estimate.

**Why use processes instead of thread timeouts?** Returning from a timed-out future does not necessarily stop its thread. A disposable process can be terminated. This still cannot undo remote side effects or guarantee descendant cleanup.

**What is similar to your Java background?** Pydantic contracts resemble DTO validation, pytest resembles JUnit, target adapters resemble strategy interfaces, and quality gates resemble build checks with domain-specific assertions. LangSmith adds experiment-oriented tracing/feedback.

**What would you improve for production?** Use representative human-reviewed datasets, semantic-judge calibration, authenticated adapters, managed isolated workers, warm-service benchmarks, statistically sound comparisons, redaction policies and a reviewed baseline-change workflow.

Read, run and modify the implementation yourself before claiming deep familiarity. Be transparent about AI-assisted development and distinguish tested local functionality from optional live integrations.
