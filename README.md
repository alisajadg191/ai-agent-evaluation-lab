# AI Agent Evaluation Lab

**Python · pytest · LangSmith · RAG evaluation · agent testing · regression gates**

A runnable evaluation framework for checking whether a RAG application or AI agent still behaves correctly after a change. It separates test inputs from reference answers, runs trusted target adapters with deadlines, scores predictions, and produces inspectable reports.

Local evaluation works **without API keys or paid model access**. The repository includes 16 fictional test cases, a passing demo target and an intentionally flawed target so you can see the framework catch real failures.

## What the project does

- Evaluates **retrieval precision/recall, citation validity, answer phrase coverage and lexical groundedness**.
- Checks **tool names, exact arguments, order, duplicate calls and forbidden tools**.
- Verifies **abstention** and rejects invalid prediction contracts.
- Records **target latency, worker wall time, errors, timeouts and local evaluation events**.
- Supports repeated runs and **per-case quality/latency regression gates**.
- Generates **JSON, HTML, Markdown, JUnit XML and JSONL event reports**.
- Optionally uses a **local Ollama model judge** for semantic support checks.
- Optionally publishes recorded datasets, predictions and feedback to **LangSmith experiments** through its Python SDK.

This is an evaluation and developer portfolio tool, not a finance adviser or an autonomous production agent. The included financial and workplace policies are synthetic fixtures, not factual guidance.

## Technologies and their roles

| Technology | Purpose |
| --- | --- |
| Python 3.11–3.13 | Framework, command-line interface, adapters and process management |
| Pydantic | Strict dataset, prediction, metric, configuration and report contracts |
| pytest | Behaviour tests, boundary checks, timeout tests and integration contract tests |
| LangSmith SDK | Optional dataset creation, recorded experiments and evaluator feedback |
| HTTPX | Optional HTTP target adapter and Ollama judge calls |
| Python multiprocessing | Fresh worker process per call and enforceable target deadline |
| JSONL + SHA-256 | Versioned datasets and comparable-run fingerprints |
| HTML / Markdown / JUnit XML | Human-readable and CI-friendly reports |
| Ruff / GitHub Actions | Lint, formatting, testing, packaging and regression smoke checks |

No vector database is required. The lab evaluates your application's retrieved document IDs against annotated reference IDs; the demo target itself uses simple lexical retrieval.

## Run locally

Install Git and Python 3.11, 3.12 or 3.13. The tested dependency versions are pinned in `requirements.lock`.

### macOS / Linux

```bash
git clone https://github.com/alisajadg191/ai-agent-evaluation-lab.git
cd ai-agent-evaluation-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps

agent-eval validate --dataset datasets/demo.jsonl
agent-eval run --dataset datasets/demo.jsonl --output reports/baseline
```

### Windows PowerShell

```powershell
git clone https://github.com/alisajadg191/ai-agent-evaluation-lab.git
cd ai-agent-evaluation-lab
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
agent-eval run --dataset datasets/demo.jsonl --output reports/baseline
```

If PowerShell activation is restricted, run `.venv\Scripts\python.exe -m evaluation_lab ...` instead of activating. On any platform, `python -m evaluation_lab` is equivalent to `agent-eval`.

Open **`reports/baseline/report.html`** in your browser. It is a self-contained static report with expandable checks; no web server is needed. A successful demo run should report **16/16 passed**. Use a new output directory for each run; the CLI does not overwrite an existing experiment directory.

To run again later, open the project folder, activate `.venv`, and run the desired command. Generated reports remain on disk and are ignored by Git.

## See a regression being caught

```bash
agent-eval run --dataset datasets/demo.jsonl \
  --target evaluation_lab.targets:flawed --output reports/candidate

agent-eval compare --baseline reports/baseline/report.json \
  --candidate reports/candidate/report.json --output reports/comparison.json
```

The flawed target invents citations/numbers, supplies incorrect tool arguments and performs forbidden synthetic calls. Its run and the comparison **intentionally return exit code 1**. This demonstrates a failing quality gate; it is not an installation failure. Use each command on one line in PowerShell.

Exit codes: **0** = pass, **1** = quality/regression failure, **2** = invalid configuration, file, contract or operation failure.

For repeated measurements:

```bash
agent-eval run --dataset datasets/demo.jsonl --repetitions 3 \
  --latency-budget-ms 2000 --timeout 10 --output reports/repeated
```

The timeout includes worker startup/imports; `latency_ms` measures only the target function. Reports show both. Successful-call p50/p95 use nearest-rank percentiles; errors/timeouts remain in quality denominators and are reported separately. Small synthetic timings are not meaningful production performance benchmarks.

## Evaluate your own application

Write a **trusted synchronous Python function** taking inputs and returning a prediction:

```python
def predict(inputs: dict) -> dict:
    # Inputs contain question, documents and payload. They never contain reference answers.
    return {
        "answer": "The limit is GBP 25. [policy]",
        "retrieved_ids": ["policy"],
        "tool_calls": [],
        "abstained": False,
    }
```

The target must be importable as `module:function` from the current Python environment. See [Python adapter](examples/python_target.py) and [HTTP adapter](examples/http_target.py).

```bash
agent-eval run --dataset datasets/demo.jsonl \
  --target examples.python_target:predict --output reports/my-app
```

The HTTP adapter sends the `Inputs` contract and expects the `Prediction` contract. Set `EVAL_TARGET_URL` and, if needed, `EVAL_TARGET_API_KEY`; then use `--target examples.http_target:predict --timeout 30`. It is not a universal adapter for arbitrary endpoint shapes—map your application's answer, sources and tool trace into the contract. Adapters execute your code with your process permissions and can access the network; subprocesses are **not security sandboxes**.

See [dataset and adapter contracts](docs/DATASETS_AND_ADAPTERS.md) for complete examples and how to connect a Finance AI Assistant or another RAG application.

## Optional semantic groundedness judge

The default `groundedness_proxy` measures token support in cited evidence. **It does not prove semantic entailment:** for example, it can miss negation. The test suite explicitly demonstrates that limitation.

For an additional, fallible model-based assessment, install and start Ollama, pull a model, then:

```bash
ollama pull llama3.2:3b
agent-eval run --dataset datasets/demo.jsonl --judge-model llama3.2:3b \
  --judge-url http://localhost:11434 --output reports/judged
```

The judge receives the question, answer and cited retrieved evidence and returns validated JSON. A malformed or unavailable judge yields an unavailable metric and fails the gate; it is never treated as a pass. This model can also be wrong or susceptible to adversarial content. Calibrate against human-labelled examples before trusting semantic scores. Live model execution is not required by CI and was not part of the initial verification.

## Optional LangSmith integration

Local runs do not automatically upload or enable tracing, even if ambient LangSmith tracing is enabled. Publication is an explicit separate command. `.env.example` lists supported variables but is **not automatically loaded**.

Set `LANGSMITH_API_KEY` in your shell or secret manager. Set `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com` for an EU workspace, and `LANGSMITH_WORKSPACE_ID` when your key requires one. Do not commit keys.

```bash
agent-eval publish --report reports/baseline/report.json \
  --project-prefix ai-agent-evaluation-lab --confirm-upload
```

This uploads **all dataset questions/documents, references, predictions and metric feedback** to the configured LangSmith account. Review the local report first; use the bundled synthetic dataset for a demo.

The integration replays **recorded results** into a named LangSmith experiment, rather than calling the application again. Therefore LangSmith's replay-run duration is **not inference latency**. Use the `measured_target_latency_ms` feedback and the local `wall_ms` field. Every case/repetition is a separate dataset example. Re-uploading the same report is blocked to avoid overwriting or duplicating a known dataset; partial-upload recovery requires inspection in LangSmith.

The real SDK evaluator conversion and upload-call contracts are tested with mocked cloud calls. No live LangSmith upload is claimed or required for the offline demo.

## Reports

| File | What it contains |
| --- | --- |
| `report.json` | Full validated dataset, predictions, config, fingerprints and metric outcomes |
| `summary.json` | Aggregate scores, pass rate, failures, unavailable counts and latency percentiles |
| `report.html` | Self-contained review page with per-case evidence |
| `report.md` | Text summary suitable for code reviews |
| `junit.xml` | Test-style results for CI tools |
| `events.jsonl` | Local completion events and durations without question/answer payloads |

Full reports intentionally contain the test content for reproducibility. Treat reports as sensitive if you use private data. Sample reports from an actual local run are included under [docs/sample-results](docs/sample-results).

## Tests and CI

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python scripts/verify_demo.py
python -m build
```

GitHub Actions runs tests and the passing/failing demo checks on supported Python versions, builds distributions, and uploads reports as workflow artifacts. The demo verification script asserts the intentionally flawed target and regression comparison fail with exit code 1; it does not hide unexpected exceptions.

## Design documentation

- [Purpose, requirements and architecture](docs/ARCHITECTURE.md)
- [Metrics, thresholds and regression semantics](docs/METRICS.md)
- [Datasets and adapter contracts](docs/DATASETS_AND_ADAPTERS.md)
- [Operations, troubleshooting and limitations](docs/OPERATIONS.md)
- [Interview walkthrough](docs/INTERVIEW_GUIDE.md)

## CV description

**AI Agent Evaluation Lab | Python, pytest, LangSmith**

Built a reproducible evaluation framework for RAG and AI agents, covering dataset validation, citation and groundedness checks, exact tool-call evaluation, regression gates, latency reporting and optional LangSmith experiments.

Run and inspect the project yourself before presenting it in interviews; be clear about lexical proxy scores, mocked cloud verification and the small synthetic dataset.
