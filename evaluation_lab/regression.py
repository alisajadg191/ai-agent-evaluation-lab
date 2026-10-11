import math
from collections import defaultdict

from evaluation_lab.reporting import expected_metric_names, percentile, summarise


def compare_reports(
    baseline, candidate, max_score_drop=0.0, max_latency_increase=0.25, latency_slack_ms=20.0
):
    if (
        any(
            not math.isfinite(v) or v < 0
            for v in [max_score_drop, max_latency_increase, latency_slack_ms]
        )
        or max_score_drop > 1
    ):
        raise ValueError("Regression tolerances must be non-negative")
    if baseline.dataset_sha256 != candidate.dataset_sha256:
        raise ValueError("Different dataset fingerprints; review changes and create a new baseline")
    if (
        baseline.scoring_sha256 != candidate.scoring_sha256
        or baseline.scorer_version != candidate.scorer_version
    ):
        raise ValueError(
            "Different evaluation settings/scorers; comparisons must use matching settings"
        )
    regressions = []

    def grouped(report):
        groups = defaultdict(list)
        for row in report.results:
            groups[row.case_id].append(row)
        return groups

    before, after = grouped(baseline), grouped(candidate)
    for case in candidate.cases:
        a, b = before[case.id], after[case.id]
        if sum(r.passed for r in b) < sum(r.passed for r in a):
            regressions.append(
                {
                    "case_id": case.id,
                    "metric": "case_pass_count",
                    "reason": "Fewer repetitions passed",
                }
            )
        for name in expected_metric_names(case, candidate.config):

            def average(rows, metric_name=name):
                return sum(
                    next(
                        (
                            m.score
                            for m in r.metrics
                            if m.name == metric_name and m.error is None and m.score is not None
                        ),
                        0,
                    )
                    if r.status == "ok"
                    else 0
                    for r in rows
                ) / len(rows)

            previous, current = average(a), average(b)
            if previous - current > max_score_drop + 1e-12:
                regressions.append(
                    {"case_id": case.id, "metric": name, "baseline": previous, "candidate": current}
                )
        previous = percentile(
            [r.latency_ms for r in a if r.status == "ok" and r.latency_ms is not None], 0.95
        )
        current = percentile(
            [r.latency_ms for r in b if r.status == "ok" and r.latency_ms is not None], 0.95
        )
        if (
            previous is not None
            and current is not None
            and current > max(previous * (1 + max_latency_increase), previous + latency_slack_ms)
        ):
            regressions.append(
                {
                    "case_id": case.id,
                    "metric": "latency_p95_ms",
                    "baseline": previous,
                    "candidate": current,
                }
            )
    return {
        "passed": not regressions and summarise(candidate)["failed"] == 0,
        "baseline_run": baseline.run_id,
        "candidate_run": candidate.run_id,
        "regressions": regressions,
        "candidate_failed_cases": summarise(candidate)["failed"],
    }
