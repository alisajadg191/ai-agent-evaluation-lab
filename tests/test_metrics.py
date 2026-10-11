import pytest

from evaluation_lab.metrics import phrase_present, score_case
from evaluation_lab.models import Case, Prediction
from evaluation_lab.targets import demo, flawed


def scores(case, prediction, config, latency=1):
    return {m.name: m for m in score_case(case, prediction, latency, config)}


def test_reference_target_passes_each_case(cases, config):
    for case in cases:
        prediction = Prediction.model_validate(demo(case.inputs.model_dump()))
        assert all(m.passed for m in score_case(case, prediction, 1, config)), case.id


def test_flawed_target_fails_each_case(cases, config):
    for case in cases:
        prediction = Prediction.model_validate(flawed(case.inputs.model_dump()))
        assert not all(m.passed for m in score_case(case, prediction, 1, config)), case.id


@pytest.mark.parametrize(
    "phrase,answer,expected",
    [
        ("25", "250", False),
        ("25", "GBP 25.", True),
        ("human approval", "HUMAN approval needed", True),
        ("0.30", "0.300", False),
        ("transfer", "transferred", False),
    ],
)
def test_phrase_boundaries(phrase, answer, expected):
    assert phrase_present(phrase, answer) == expected


def test_invalid_citation_fails(cases, config):
    prediction = Prediction(answer="The limit is GBP 25. [fake]", retrieved_ids=["meal-cap-source"])
    result = scores(cases[0], prediction, config)
    assert result["citation_validity"].score == 0
    assert result["groundedness_proxy"].score == 0


def test_uncited_retrieved_source_cannot_support_answer(cases, config):
    prediction = Prediction(answer="The limit is GBP 25.", retrieved_ids=["meal-cap-source"])
    assert scores(cases[0], prediction, config)["groundedness_proxy"].score == 0


def test_unretrieved_citation_fails(cases, config):
    prediction = Prediction(answer="GBP 25 [meal-cap-source]")
    assert scores(cases[0], prediction, config)["citation_validity"].score == 0


def test_invented_number_fails_grounding(cases, config):
    prediction = Prediction(
        answer="The limit is GBP 999. [meal-cap-source]", retrieved_ids=["meal-cap-source"]
    )
    assert scores(cases[0], prediction, config)["groundedness_proxy"].score == 0


def test_retrieval_precision_and_recall(config):
    case = Case(
        id="multi",
        task="rag",
        inputs={
            "question": "cap?",
            "documents": [
                {"id": "a", "text": "Cap 25"},
                {"id": "b", "text": "Other 40"},
                {"id": "c", "text": "Unrelated"},
            ],
        },
        reference={"answer_contains": ["25"], "relevant_document_ids": ["a", "b"]},
    )
    prediction = Prediction(answer="Cap 25 [a]", retrieved_ids=["a", "c"])
    result = scores(case, prediction, config)
    assert result["retrieval_precision"].score == 0.5
    assert result["retrieval_recall"].score == 0.5


@pytest.mark.parametrize("ids", [["meal-cap-source", "meal-cap-source"], ["invented"]])
def test_retrieval_integrity(cases, config, ids):
    result = scores(
        cases[0], Prediction(answer="GBP 25 [meal-cap-source]", retrieved_ids=ids), config
    )
    assert not result["retrieval_integrity"].passed


def tool_case(order="ordered"):
    return Case(
        id="tools",
        task="agent",
        inputs={"question": "workflow"},
        reference={
            "tool_order": order,
            "expected_tools": [
                {"name": "lookup", "arguments": {"id": 1}},
                {"name": "summarise", "arguments": {"id": 1}},
            ],
            "forbidden_tools": ["transfer"],
        },
    )


def test_tool_order_and_unordered_mode(config):
    prediction = Prediction(
        answer="done", tool_calls=list(reversed(tool_case().reference.expected_tools))
    )
    assert not scores(tool_case(), prediction, config)["tool_call_correctness"].passed
    assert scores(tool_case("unordered"), prediction, config)["tool_call_correctness"].passed


def test_duplicate_tool_calls_are_not_hidden(config):
    case = tool_case("unordered")
    prediction = Prediction(
        answer="done", tool_calls=case.reference.expected_tools + [case.reference.expected_tools[0]]
    )
    assert not scores(case, prediction, config)["tool_call_correctness"].passed


@pytest.mark.parametrize("value", [True, "1", 2])
def test_tool_argument_types_and_values(config, value):
    case = tool_case()
    prediction = Prediction(
        answer="done",
        tool_calls=[
            {"name": "lookup", "arguments": {"id": value}},
            case.reference.expected_tools[1],
        ],
    )
    assert not scores(case, prediction, config)["tool_call_correctness"].passed


def test_forbidden_tool_fails_even_if_answer_correct(config):
    prediction = Prediction(answer="done", tool_calls=[{"name": "transfer", "arguments": {}}])
    assert not scores(tool_case(), prediction, config)["forbidden_tool_safety"].passed


def test_latency_budget_boundary(cases, config):
    prediction = Prediction.model_validate(demo(cases[0].inputs.model_dump()))
    assert scores(cases[0], prediction, config, 2000)["latency_budget"].passed
    assert not scores(cases[0], prediction, config, 2000.01)["latency_budget"].passed


def test_proxy_limitation_is_explicit(config):
    case = Case(
        id="negation",
        task="rag",
        inputs={
            "question": "safe?",
            "documents": [{"id": "policy", "text": "The action is not permitted."}],
        },
        reference={"answer_contains": ["permitted"], "relevant_document_ids": ["policy"]},
    )
    result = scores(
        case,
        Prediction(answer="The action is permitted. [policy]", retrieved_ids=["policy"]),
        config,
    )
    # This intentionally demonstrates why token overlap MUST NOT be advertised as entailment.
    assert result["groundedness_proxy"].score == 1
    assert "does not prove entailment" in result["groundedness_proxy"].reason
