"""Explicit publication of recorded local results, not a second target execution."""

import os
import re

from evaluation_lab.models import CaseResult
from evaluation_lab.reporting import expected_metric_names


def publish_report(report, prefix="ai-agent-evaluation-lab", client=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", prefix):
        raise ValueError("Project prefix must be 1–60 letters, digits, underscores or hyphens")
    owned_client = client is None
    if owned_client:
        if not os.getenv("LANGSMITH_API_KEY"):
            raise ValueError("Set LANGSMITH_API_KEY before publishing")
        from langsmith import Client

        client = Client()
    name = f"{prefix}-{report.run_id}"
    try:
        if client.has_dataset(dataset_name=name):
            raise ValueError(
                "This report already has a LangSmith dataset; inspect the existing upload before retrying"
            )
        dataset = client.create_dataset(
            dataset_name=name,
            description=(
                "Recorded local evaluation results. Each row is one case/repetition. "
                "Target runtime is stored as feedback; LangSmith replay duration is not inference latency."
            ),
        )
        cases = {c.id: c for c in report.cases}
        records = {(r.case_id, r.repetition): r for r in report.results}
        examples = [
            {
                "inputs": {
                    "case_id": r.case_id,
                    "repetition": r.repetition,
                    "request": cases[r.case_id].inputs.model_dump(mode="json"),
                },
                "outputs": {
                    "task": cases[r.case_id].task,
                    "reference": cases[r.case_id].reference.model_dump(mode="json"),
                },
            }
            for r in report.results
        ]
        client.create_examples(dataset_id=dataset.id, examples=examples)

        def recorded_target(inputs):
            return records[(inputs["case_id"], inputs["repetition"])].model_dump(mode="json")

        def local_metrics(inputs, outputs, reference_outputs):
            row = CaseResult.model_validate(outputs)
            metrics = {m.name: m for m in row.metrics}
            feedback = []
            for key in expected_metric_names(cases[inputs["case_id"]], report.config):
                m = metrics.get(key)
                available = (
                    row.status == "ok" and m is not None and m.score is not None and m.error is None
                )
                feedback.append(
                    {
                        "key": key,
                        "score": m.score if available else 0,
                        "comment": m.reason
                        if available
                        else "Unavailable or target failed; scored zero",
                    }
                )
            feedback.append({"key": "case_passed", "score": float(row.passed)})
            if row.latency_ms is not None:
                feedback.append(
                    {
                        "key": "measured_target_latency_ms",
                        "score": row.latency_ms,
                        "comment": "Measured in the original local target execution, excludes worker startup.",
                    }
                )
            return {"results": feedback}

        results = client.evaluate(
            recorded_target,
            data=name,
            evaluators=[local_metrics],
            experiment_prefix=f"{prefix}-recorded",
            max_concurrency=1,
            num_repetitions=1,
            upload_results=True,
            metadata={
                "source": "recorded-local-report",
                "run_id": report.run_id,
                "dataset_sha256": report.dataset_sha256,
                "scorer_version": report.scorer_version,
                "target": report.config.target,
            },
        )
        # The SDK blocks by default; iterating also ensures recorded evaluations are consumed.
        for _ in results:
            pass
        return {
            "dataset_name": name,
            "experiment_name": results.experiment_name,
            "replayed_results": len(report.results),
        }
    finally:
        if owned_client:
            client.close()
