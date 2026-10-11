from pathlib import Path

import pytest

from evaluation_lab.datasets import dataset_digest, load_dataset, scoring_digest
from evaluation_lab.metrics import score_case
from evaluation_lab.models import CaseResult, Prediction, Report, RunConfig
from evaluation_lab.targets import demo


@pytest.fixture
def cases():
    return load_dataset(Path(__file__).parents[1] / "datasets/demo.jsonl")


@pytest.fixture
def config():
    return RunConfig(target="evaluation_lab.targets:demo")


@pytest.fixture
def report(cases, config):
    results = []
    for case in cases:
        prediction = Prediction.model_validate(demo(case.inputs.model_dump()))
        results.append(
            CaseResult(
                case_id=case.id,
                repetition=0,
                status="ok",
                prediction=prediction,
                latency_ms=10,
                wall_ms=20,
                metrics=score_case(case, prediction, 10, config),
            )
        )
    return Report(
        run_id="test-run",
        created_at="2026-10-10T00:00:00Z",
        dataset_sha256=dataset_digest(cases),
        scoring_sha256=scoring_digest(config),
        config=config,
        cases=cases,
        results=results,
    )
