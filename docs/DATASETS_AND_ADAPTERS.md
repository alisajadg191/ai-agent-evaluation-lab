# Datasets and adapter contracts

## Dataset format

One JSON object per line, UTF-8 `.jsonl`. The loader accepts 1–1000 cases and files up to 10 MB. Case IDs and document IDs use letters, digits, hyphens or underscores. RAG references must point to input documents and include at least one expected answer phrase.

```json
{
  "id": "meal-policy",
  "task": "rag",
  "inputs": {
    "question": "What is the meal limit?",
    "documents": [{"id": "policy", "text": "The meal limit is GBP 25."}],
    "payload": {}
  },
  "reference": {
    "answer_contains": ["GBP 25"],
    "relevant_document_ids": ["policy"],
    "expected_tools": [],
    "tool_order": "ordered",
    "forbidden_tools": ["transfer_money"]
  },
  "tags": ["synthetic", "policy"]
}
```

The formatted example above is for reading; save each case on one line in a dataset. `schema_version` defaults to `1.0`. Valid tasks are `rag`, `agent` and `abstention`. The generated [JSON Schema](../datasets/case.schema.json) describes all fields and constraints.

## Target contract

The adapter receives only:

```json
{"question":"What is the meal limit?","documents":[{"id":"policy","text":"The meal limit is GBP 25."}],"payload":{}}
```

It returns:

```json
{
  "answer": "The meal limit is GBP 25. [policy]",
  "retrieved_ids": ["policy"],
  "tool_calls": [],
  "abstained": false
}
```

Only `answer` is required; other prediction fields have explicit defaults. The strict boolean `abstained` must reflect application behaviour, not evaluator inference. Unknown output fields fail validation. A non-RAG agent can leave `retrieved_ids` empty. Citations use `[document-id]` syntax.

## Agent example

```json
{
  "id": "add-money",
  "task": "agent",
  "inputs": {"question": "Add these amounts", "payload": {"numbers": ["0.10", "0.20"]}},
  "reference": {
    "answer_contains": ["0.30"],
    "expected_tools": [{"name": "add", "arguments": {"numbers": ["0.10", "0.20"]}}],
    "forbidden_tools": ["transfer_money"]
  }
}
```

Tool traces must come from your application's actual structured execution log, not an LLM's narrative description. The evaluator compares reported traces but cannot independently verify external side effects.

## Integrating other projects

For a RAG service, create annotated fixtures from a fixed synthetic corpus, make the adapter call your service, and map its source IDs to the fixture document IDs. For the Finance AI Assistant, its chat response contains `answer`, `citations`, `mode` and optional `tool_result`; write an adapter to normalise those fields into `Prediction`. Its chunk citations include suffixes, so map chunk IDs to source document IDs consistently in both the answer and retrieval list.

Do not infer an entire tool trace from a final `tool_result` field when the application does not expose one. Either instrument the real calls or restrict that dataset to RAG/answer checks. Do not reuse the bundled demo references against a service with a different corpus and call the result comparable.

Async applications need a synchronous wrapper, for example a function using `asyncio.run()` to invoke your coroutine. The framework itself expects a synchronous callable. The HTTP adapter is often simpler when evaluating a running async web service.

## Dataset review checklist

- Are the references correct and independently reviewed?
- Is the dataset representative rather than tailored only to the demo target?
- Are unsupported questions, extra tools, wrong arguments and malicious-looking instructions represented?
- Are source IDs stable and relevant-source annotations complete?
- Is all data synthetic or permitted for local storage and any optional cloud upload?
- Has every changed reference triggered a reviewed new baseline?

The bundled 16-case dataset validates the lab and supports demonstrations; it is not a broad model benchmark.
