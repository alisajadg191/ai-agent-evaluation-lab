import html
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from evaluation_lab.datasets import canonical, dataset_digest, scoring_digest
from evaluation_lab.metrics import score_case
from evaluation_lab.models import Prediction, Report


def percentile(values, quantile):
    """Nearest-rank percentile; None for an empty set."""
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * quantile) - 1)]


def expected_metric_names(case, config):
    names = [m.name for m in score_case(case, Prediction(answer="unknown"), 0, config)]
    if config.judge_model and case.task == "rag":
        names.append("groundedness_judge")
    return names


def summarise(report):
    cases = {c.id: c for c in report.cases}
    totals = defaultdict(list)
    unavailable = defaultdict(int)
    for row in report.results:
        actual = {m.name: m for m in row.metrics}
        for name in expected_metric_names(cases[row.case_id], report.config):
            metric = actual.get(name)
            if row.status != "ok" or metric is None or metric.error or metric.score is None:
                totals[name].append(0)
                unavailable[name] += 1
            else:
                totals[name].append(metric.score)
    latencies = [
        r.latency_ms for r in report.results if r.status == "ok" and r.latency_ms is not None
    ]
    count = len(report.results)
    passed = sum(r.passed for r in report.results)
    return {
        "total": count,
        "passed": passed,
        "failed": count - passed,
        "pass_rate": passed / count,
        "errors": sum(r.status == "error" for r in report.results),
        "timeouts": sum(r.status == "timeout" for r in report.results),
        "latency_samples": len(latencies),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
        "metrics": {
            name: {
                "mean": sum(scores) / len(scores),
                "samples": len(scores),
                "unavailable": unavailable[name],
            }
            for name, scores in sorted(totals.items())
        },
    }


def load_report(path):
    path = Path(path)
    if path.stat().st_size > 100_000_000:
        raise ValueError("Report exceeds 100 MB")
    report = Report.model_validate_json(path.read_text(encoding="utf-8"))
    if report.dataset_sha256 != dataset_digest(
        report.cases
    ) or report.scoring_sha256 != scoring_digest(report.config):
        raise ValueError("Report fingerprint mismatch")
    for row in report.results:
        case = next(c for c in report.cases if c.id == row.case_id)
        if row.status == "ok" and (
            row.prediction is None
            or row.latency_ms is None
            or {m.name for m in row.metrics} != set(expected_metric_names(case, report.config))
            or len(row.metrics) != len({m.name for m in row.metrics})
        ):
            raise ValueError(
                "Successful result must contain prediction, latency and every applicable metric"
            )
    return report


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as temp:
            name = temp.name
            temp.write(text)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def write_reports(report, events, directory):
    directory = Path(directory)
    summary = summarise(report)
    atomic_write(directory / "report.json", report.model_dump_json(indent=2) + "\n")
    atomic_write(directory / "summary.json", json.dumps(summary, indent=2) + "\n")
    atomic_write(directory / "events.jsonl", "\n".join(canonical(e) for e in events) + "\n")
    lines = [
        "# Evaluation report",
        "",
        f"Target: `{report.config.target}`",
        "",
        f"Passed: **{summary['passed']}/{summary['total']}**. Errors: {summary['errors']}; timeouts: {summary['timeouts']}.",
        "",
        "| Metric | Mean | Samples | Unavailable |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, metric in summary["metrics"].items():
        lines.append(
            f"| {name} | {metric['mean']:.3f} | {metric['samples']} | {metric['unavailable']} |"
        )
    lines.extend(
        [
            "",
            "Lexical groundedness is a proxy. Failures and unavailable metrics count as zero; latency percentiles use successful calls only.",
            "",
            f"Target latency p50: {summary['latency_p50_ms']} ms; p95: {summary['latency_p95_ms']} ms.",
            "",
            "| Case / repeat | Result | Failed checks |",
            "| --- | --- | --- |",
        ]
    )
    for row in report.results:
        failed = ", ".join(m.name for m in row.metrics if not m.passed) or row.error_type or "—"
        lines.append(
            f"| {row.case_id} / {row.repetition} | {'PASS' if row.passed else 'FAIL'} | {failed} |"
        )
    atomic_write(directory / "report.md", "\n".join(lines) + "\n")
    atomic_write(directory / "report.html", render_html(report, summary))
    suite = ET.Element(
        "testsuite",
        name="agent-evaluation",
        tests=str(summary["total"]),
        failures=str(sum(not r.passed and r.status == "ok" for r in report.results)),
        errors=str(summary["errors"] + summary["timeouts"]),
    )
    for row in report.results:
        test = ET.SubElement(
            suite,
            "testcase",
            classname="evaluation",
            name=f"{row.case_id}[{row.repetition}]",
            time=str((row.latency_ms or row.wall_ms) / 1000),
        )
        if row.status != "ok":
            ET.SubElement(test, "error", message=row.error_type or row.status)
        elif not row.passed:
            ET.SubElement(
                test, "failure", message=", ".join(m.name for m in row.metrics if not m.passed)
            )
    atomic_write(directory / "junit.xml", ET.tostring(suite, encoding="unicode"))


def render_html(report, summary):
    escape = html.escape
    cards = "".join(
        f"<article><span>{escape(label)}</span><strong>{escape(str(value))}</strong></article>"
        for label, value in [
            ("Cases passed", f"{summary['passed']} / {summary['total']}"),
            ("Pass rate", f"{summary['pass_rate']:.0%}"),
            ("Errors / timeouts", f"{summary['errors']} / {summary['timeouts']}"),
            (
                "Target p95",
                f"{summary['latency_p95_ms']:.2f} ms"
                if summary["latency_p95_ms"] is not None
                else "Unavailable",
            ),
        ]
    )
    rows = ""
    for result in report.results:
        checks = "".join(
            f"<li><b>{escape(m.name)}</b>: {m.score if m.score is not None else 'unavailable'} / threshold {m.threshold}<br>{escape(m.reason)}</li>"
            for m in result.metrics
        )
        answer = escape(
            result.prediction.answer if result.prediction else result.error_type or result.status
        )
        status = "PASS" if result.passed else "FAIL"
        rows += (
            f'<tr><td>{escape(result.case_id)}<small>Repeat {result.repetition + 1}</small></td><td class="{status.lower()}">{status}</td><td>{result.latency_ms:.2f} ms</td><td><details><summary>Inspect answer & checks</summary><pre>{answer}</pre><ul>{checks}</ul></details></td></tr>'
            if result.latency_ms is not None
            else f'<tr><td>{escape(result.case_id)}</td><td class="fail">{status}</td><td>Unavailable</td><td>{answer}</td></tr>'
        )
    metrics = "".join(
        f"<tr><td>{escape(name)}</td><td>{value['mean']:.3f}</td><td>{value['samples']}</td><td>{value['unavailable']}</td></tr>"
        for name, value in summary["metrics"].items()
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>AI Agent Evaluation Lab — report</title><style>
    *{{box-sizing:border-box}}body{{font:14px system-ui,sans-serif;background:#f3f5f9;color:#202b43;margin:0}}main{{max-width:1180px;margin:auto;padding:48px 24px}}header{{border-bottom:1px solid #d8deea;padding-bottom:28px;margin-bottom:25px}}.eyebrow{{font-size:11px;letter-spacing:2px;color:#5c63bc;font-weight:700}}h1{{font-size:38px;letter-spacing:-1.5px;margin:12px 0}}p{{color:#68748a;line-height:1.7}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}}article,section{{background:white;border:1px solid #e0e4ef;border-radius:12px;padding:22px}}article span{{display:block;color:#6a758a;font-size:12px}}article strong{{display:block;font-size:28px;margin-top:10px}}section{{margin-top:24px;overflow:auto}}h2{{font-size:19px;margin:0 0 20px}}table{{width:100%;border-collapse:collapse;text-align:left}}th{{color:#7b8494;font-size:11px;text-transform:uppercase;letter-spacing:1px}}td,th{{padding:14px 10px;border-bottom:1px solid #edf0f5}}small{{display:block;color:#8a94a4;margin-top:5px}}.pass{{color:#227963;font-weight:700}}.fail{{color:#b1484e;font-weight:700}}summary{{cursor:pointer;color:#5c63bc}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6fa;padding:15px;border-radius:8px;max-width:520px}}li{{margin-bottom:14px;line-height:1.6}}footer{{font-size:11px;color:#8891a3;margin-top:25px}}@media(max-width:700px){{.cards{{grid-template-columns:1fr 1fr}}h1{{font-size:29px}}main{{padding:28px 15px}}}}
    </style></head><body><main><header><div class="eyebrow">AI AGENT EVALUATION LAB</div><h1>Evidence before deployment.</h1><p>Target: {escape(report.config.target)}<br>{escape(report.created_at)} · {escape(report.run_id)}</p></header><div class="cards">{cards}</div><section><h2>Quality metrics</h2><table><thead><tr><th>Metric</th><th>Mean</th><th>Samples</th><th>Unavailable</th></tr></thead><tbody>{metrics}</tbody></table><p>Groundedness proxy measures lexical support, not semantic entailment. Failed or unavailable metrics count as zero. Latency percentiles exclude failed target calls.</p></section><section><h2>Case results</h2><table><thead><tr><th>Case</th><th>Result</th><th>Target latency</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table></section><footer>Dataset SHA-256: {escape(report.dataset_sha256)} · Scorer {escape(report.scorer_version)} · Static report; no scripts or external requests.</footer></main></body></html>"""
