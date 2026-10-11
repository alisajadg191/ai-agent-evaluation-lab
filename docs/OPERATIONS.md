# Operations and troubleshooting

## Local-first behaviour

The default runner evaluates bundled targets without model access. It explicitly disables LangSmith tracing inside its own worker context. It cannot prevent a custom adapter from making its own network calls or overriding tracing; inspect adapters before execution. The CLI never uses `eval`, a shell string or arbitrary code from dataset fields.

Each run needs an empty/new output directory. Reports contain inputs and predictions; event files omit those payloads but contain case IDs and scores. Protect report directories if fixtures contain confidential information. Individual report writes are atomic; a failure while writing multiple formats can still leave a partial directory, so inspect it and choose a new directory for a rerun.

## LangSmith publication

Supply your own account credentials via environment variables and choose the correct region. `--confirm-upload` explicitly opts into uploading the report's complete data. The project does not auto-load `.env` or upload during tests/CI.

Each report gets a dataset named from the project prefix and run ID. Existing names are rejected. A network failure can leave a partial dataset or experiment; inspect the LangSmith UI before any cleanup or retry. The lab never silently overwrites or deletes cloud datasets. A live cloud roundtrip needs an account and was not executed during initial offline verification.

## Runtime limits

- Trusted synchronous Python adapters only. Subprocess isolation is for deadlines/state separation, not hostile-code sandboxing.
- Sequential execution with a fresh process per case/repetition; no concurrency/load-test claim.
- The timeout includes imports and startup. Increase it for slow machines while keeping baseline/candidate settings identical.
- A terminated worker may have already caused external side effects. Use read-only endpoints or an isolated synthetic test environment.
- Ollama judge calls have an HTTP timeout, but it is not a distributed hard deadline. Judge time is separate from target latency.
- Report fingerprints are reproducibility checks, not cryptographic signatures. Do not accept externally edited report scores as trusted evidence.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `agent-eval` not found | Activate `.venv`, install with `pip install -e . --no-deps`, or use `python -m evaluation_lab` |
| Import/module error in results | Run from the repository root or install your adapter package; use `module:function` syntax |
| Every case times out | Raise `--timeout`; imports/startup are included; inspect target independently in a safe environment |
| Invalid dataset line | Validate the JSONL row against `datasets/case.schema.json`; one object per line |
| Report fingerprint mismatch | The data/config changed or serialization was altered; rerun from validated input |
| Comparison refuses settings | Match repetitions, thresholds, timeout, latency budget and judge settings |
| Flawed target exits 1 | Expected; this is the negative demonstration |
| Ollama judge unavailable | Start Ollama, pull the named model and check `--judge-url` |
| Publication refuses upload | Add `--confirm-upload` only after reviewing report content and configure `LANGSMITH_API_KEY` |
| Existing LangSmith dataset | Inspect the previous/partial upload; use a new evaluated report for a new experiment |

## Validation boundaries

Automated tests exercise deterministic evaluators, contract errors, real worker execution, timeout cancellation, report formats, regression checks, mocked HTTP providers and the real LangSmith evaluator adapter interface. They do not claim successful live cloud publication or semantic model quality. CI exercises the complete positive/negative CLI pipeline and packaging.
