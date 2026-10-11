import pytest

from evaluation_lab.datasets import scoring_digest
from evaluation_lab.models import RunConfig
from evaluation_lab.regression import compare_reports
from evaluation_lab.runner import execute_target, load_target, run_evaluation


def test_execution_success_without_reference_leakage(cases):
    assert set(cases[0].inputs.model_dump()) == {"question", "documents", "payload"}
    result = execute_target("evaluation_lab.targets:demo", cases[0].inputs.model_dump(), 10)
    assert result["status"] == "ok" and result["latency_ms"] >= 0 and result["wall_ms"] > 0


@pytest.mark.parametrize(
    "target,expected", [("crashing", "RuntimeError"), ("invalid", "ValidationError")]
)
def test_target_failures_sanitised(cases, target, expected):
    result = execute_target("evaluation_lab.targets:" + target, cases[0].inputs.model_dump(), 10)
    assert result["status"] == "error" and result["error_type"] == expected
    assert "Synthetic failure" not in str(result)


def test_hard_timeout(cases):
    result = execute_target("evaluation_lab.targets:slow", cases[0].inputs.model_dump(), 0.2)
    assert result["status"] == "timeout" and result["wall_ms"] < 2000


@pytest.mark.parametrize("spec", ["os.system", "os:system;rm", "not_a_real_module:function"])
def test_invalid_targets(spec):
    with pytest.raises((ValueError, ImportError)):
        load_target(spec)


def test_repetitions_and_events(cases):
    report, events = run_evaluation(
        cases[:1], RunConfig(target="evaluation_lab.targets:demo", repetitions=2)
    )
    assert len(report.results) == 2 and len(events) == 4
    assert {r.repetition for r in report.results} == {0, 1}
    assert all(r.passed for r in report.results)
    assert all("question" not in e and "answer" not in e for e in events)


def test_no_change_passes(report):
    assert compare_reports(report, report)["passed"]


def test_metric_regression_detected(report):
    candidate = report.model_copy(deep=True)
    candidate.results[0].metrics[-1].score = 0
    result = compare_reports(report, candidate)
    assert not result["passed"]
    assert any(r["metric"] == "groundedness_proxy" for r in result["regressions"])


def test_latency_regression_and_slack(report):
    candidate = report.model_copy(deep=True)
    candidate.results[0].latency_ms = 29
    assert compare_reports(report, candidate)["passed"]
    candidate.results[0].latency_ms = 31
    assert not compare_reports(report, candidate)["passed"]


def test_different_data_rejected(report):
    candidate = report.model_copy(update={"dataset_sha256": "different"})
    with pytest.raises(ValueError, match="dataset"):
        compare_reports(report, candidate)


def test_different_settings_rejected(report):
    candidate = report.model_copy(deep=True)
    candidate.config.repetitions = 2
    candidate.scoring_sha256 = scoring_digest(candidate.config)
    with pytest.raises(ValueError, match="settings"):
        compare_reports(report, candidate)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_bad_tolerances(report, value):
    with pytest.raises(ValueError):
        compare_reports(report, report, max_score_drop=value)


def test_bad_candidate_fails_even_without_new_regression(report):
    report.results[0].metrics[0].score = 0
    result = compare_reports(report, report)
    assert not result["passed"] and result["regressions"] == []
