from xml.etree import ElementTree as ET

import pytest

from evaluation_lab.datasets import dataset_digest, load_dataset, scoring_digest
from evaluation_lab.models import Case, Prediction, Report, RunConfig
from evaluation_lab.reporting import load_report, percentile, render_html, summarise, write_reports


def test_dataset_fingerprint_order_independent(cases):
    assert dataset_digest(cases) == dataset_digest(list(reversed(cases)))
    changed = cases[0].model_copy(deep=True)
    changed.reference.answer_contains.append("changed")
    assert dataset_digest([changed, *cases[1:]]) != dataset_digest(cases)


def test_target_not_in_scoring_fingerprint(config):
    other = config.model_copy(update={"target": "evaluation_lab.targets:flawed"})
    assert scoring_digest(config) == scoring_digest(other)
    assert scoring_digest(config) != scoring_digest(
        config.model_copy(update={"grounding_threshold": 0.9})
    )


@pytest.mark.parametrize("body", ["", "not json\n", "{}\n"])
def test_invalid_dataset(tmp_path, body):
    path = tmp_path / "data.jsonl"
    path.write_text(body)
    with pytest.raises(ValueError):
        load_dataset(path)


def test_duplicate_case_ids(tmp_path, cases):
    path = tmp_path / "data.jsonl"
    path.write_text(cases[0].model_dump_json() + "\n" + cases[0].model_dump_json())
    with pytest.raises(ValueError, match="unique"):
        load_dataset(path)


def test_missing_reference_doc_rejected(cases):
    data = cases[0].model_dump()
    data["reference"]["relevant_document_ids"] = ["missing"]
    with pytest.raises(ValueError):
        Case.model_validate(data)


def test_duplicate_documents_rejected(cases):
    data = cases[0].model_dump()
    data["inputs"]["documents"] *= 2
    with pytest.raises(ValueError):
        Case.model_validate(data)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0])
def test_invalid_timeout(bad):
    with pytest.raises(ValueError):
        RunConfig(target="evaluation_lab.targets:demo", timeout_seconds=bad)


def test_strict_abstention():
    with pytest.raises(ValueError):
        Prediction(answer="unknown", abstained="false")


def test_report_roundtrip_and_junit(tmp_path, report):
    write_reports(report, [], tmp_path)
    loaded = load_report(tmp_path / "report.json")
    assert loaded == report
    assert set(p.name for p in tmp_path.iterdir()) == {
        "report.json",
        "summary.json",
        "report.md",
        "report.html",
        "junit.xml",
        "events.jsonl",
    }
    root = ET.parse(tmp_path / "junit.xml").getroot()
    assert root.attrib["tests"] == "16" and root.attrib["failures"] == "0"


def test_report_rejects_missing_results(report):
    data = report.model_dump()
    data["results"].pop()
    with pytest.raises(ValueError):
        Report.model_validate(data)


def test_report_rejects_duplicate_results(report):
    data = report.model_dump()
    data["results"][-1] = data["results"][0]
    with pytest.raises(ValueError):
        Report.model_validate(data)


def test_report_rejects_changed_fingerprint(tmp_path, report):
    report.dataset_sha256 = "fake"
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())
    with pytest.raises(ValueError, match="fingerprint"):
        load_report(path)


def test_report_rejects_missing_metrics(tmp_path, report):
    report.results[0].metrics = []
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())
    with pytest.raises(ValueError, match="every applicable metric"):
        load_report(path)


def test_failures_not_removed_from_aggregate(report):
    report.results[0].status = "error"
    report.results[0].prediction = None
    report.results[0].metrics = []
    result = summarise(report)
    assert result["total"] == 16 and result["passed"] == 15 and result["errors"] == 1
    assert result["metrics"]["citation_validity"]["samples"] == 7
    assert result["metrics"]["citation_validity"]["unavailable"] == 1
    assert result["metrics"]["citation_validity"]["mean"] == pytest.approx(6 / 7)
    assert result["latency_samples"] == 15


def test_html_escapes_untrusted_outputs(report):
    report.results[0].prediction.answer = '<script>alert("x")</script>'
    output = render_html(report, summarise(report))
    assert "<script>" not in output and "&lt;script&gt;" in output
    assert "default-src 'none'" in output


def test_percentiles():
    assert percentile([], 0.95) is None
    assert percentile([1], 0.95) == 1
    assert percentile(list(range(1, 101)), 0.95) == 95
