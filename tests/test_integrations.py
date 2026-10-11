from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langsmith.evaluation import run_evaluator
from langsmith.schemas import Example, Run

from evaluation_lab.cli import main
from evaluation_lab.judge import judge_grounding
from evaluation_lab.langsmith_integration import publish_report
from evaluation_lab.models import Prediction
from evaluation_lab.targets import demo


class FakeClient:
    def __init__(self):
        self.calls = []
        self.exists = False
        self.examples = []
        self.feedback = []

    def has_dataset(self, **kwargs):
        self.calls.append("has_dataset")
        return self.exists

    def create_dataset(self, **kwargs):
        self.calls.append("create_dataset")
        return SimpleNamespace(id=uuid4())

    def create_examples(self, **kwargs):
        self.calls.append("create_examples")
        self.examples = kwargs["examples"]

    def evaluate(self, target, **kwargs):
        self.calls.append("evaluate")
        assert kwargs["metadata"]["source"] == "recorded-local-report"
        evaluator = run_evaluator(kwargs["evaluators"][0])
        for entry in self.examples:
            outputs = target(entry["inputs"])
            now = datetime.now(timezone.utc)
            run = Run(
                id=uuid4(),
                name="recorded",
                run_type="chain",
                start_time=now,
                inputs=entry["inputs"],
                outputs=outputs,
            )
            example = Example(
                id=uuid4(),
                dataset_id=uuid4(),
                created_at=now,
                inputs=entry["inputs"],
                outputs=entry["outputs"],
            )
            # Exercise LangSmith's real evaluator signature/result conversion without network.
            self.feedback.append(evaluator.evaluate_run(run, example))

        class Results(list):
            experiment_name = "test-recorded-experiment"

        return Results(self.feedback)


def test_langsmith_replays_results_through_real_sdk_evaluator(report):
    client = FakeClient()
    result = publish_report(report, client=client)
    assert result["replayed_results"] == 16
    assert result["experiment_name"] == "test-recorded-experiment"
    assert len(client.feedback) == 16
    assert client.calls == ["has_dataset", "create_dataset", "create_examples", "evaluate"]
    assert "reference" not in client.examples[0]["inputs"]["request"]
    assert "reference" in client.examples[0]["outputs"]


def test_duplicate_publication_does_not_mutate(report):
    client = FakeClient()
    client.exists = True
    with pytest.raises(ValueError, match="already"):
        publish_report(report, client=client)
    assert client.calls == ["has_dataset"]


def test_missing_key_and_opt_in(report, monkeypatch, capsys):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        publish_report(report)
    assert main(["publish", "--report", "unused.json"]) == 2
    assert "--confirm-upload" in capsys.readouterr().err


def test_judge_supports_structured_output(cases, config, monkeypatch):
    config.judge_model = "test-model"
    prediction = Prediction.model_validate(demo(cases[0].inputs.model_dump()))

    def post(url, **kwargs):
        assert url.endswith("/api/chat")
        assert kwargs["json"]["format"]["properties"]["supported"]["type"] == "boolean"
        assert "untrusted data" in kwargs["json"]["messages"][0]["content"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "message": {
                    "content": '{"supported":true,"explanation":"Supported by the cited excerpt."}'
                }
            },
        )

    monkeypatch.setattr("evaluation_lab.judge.httpx.post", post)
    result = judge_grounding(cases[0], prediction, config)
    assert result.score == 1 and result.passed


@pytest.mark.parametrize(
    "payload", ["not json", '{"supported":"yes","explanation":"x"}', '{"supported":true}']
)
def test_invalid_judge_output_fails_closed(cases, config, monkeypatch, payload):
    monkeypatch.setattr(
        "evaluation_lab.judge.httpx.post",
        lambda url, **kw: httpx.Response(
            200, request=httpx.Request("POST", url), json={"message": {"content": payload}}
        ),
    )
    prediction = Prediction.model_validate(demo(cases[0].inputs.model_dump()))
    result = judge_grounding(cases[0], prediction, config)
    assert result.score is None and result.error and not result.passed


def test_judge_outage_fails_closed(cases, config, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("secret-bearing provider payload")

    monkeypatch.setattr("evaluation_lab.judge.httpx.post", fail)
    result = judge_grounding(
        cases[0], Prediction.model_validate(demo(cases[0].inputs.model_dump())), config
    )
    assert not result.passed and result.error == "ConnectError"
    assert "secret-bearing" not in result.model_dump_json()


def test_no_evidence_does_not_call_judge(cases, config, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("No evidence must not invoke the judge")

    monkeypatch.setattr("evaluation_lab.judge.httpx.post", fail)
    assert judge_grounding(cases[0], Prediction(answer="invented"), config).score == 0


def test_local_run_does_not_publish(monkeypatch, cases, config):
    from evaluation_lab.runner import run_evaluation

    def fail(*args, **kwargs):
        pytest.fail("Local run must not call cloud publication")

    monkeypatch.setattr("evaluation_lab.langsmith_integration.publish_report", fail)
    report, _ = run_evaluation(cases[:1], config)
    assert report.results[0].passed


def test_http_adapter(monkeypatch):
    from examples.http_target import predict

    monkeypatch.setenv("EVAL_TARGET_URL", "http://localhost:8000/predict")

    def post(url, **kwargs):
        assert kwargs["json"] == {"question": "hello"}
        return httpx.Response(200, request=httpx.Request("POST", url), json={"answer": "hello"})

    monkeypatch.setattr("examples.http_target.httpx.post", post)
    assert predict({"question": "hello"}) == {"answer": "hello"}
