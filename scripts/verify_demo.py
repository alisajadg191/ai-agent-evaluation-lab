"""Exercise the CLI's positive and negative quality gates; fail on any unexpected exit."""

import json
import subprocess
import sys
from pathlib import Path


def main():
    base = Path("reports/ci-demo")
    if base.exists():
        raise SystemExit(
            "reports/ci-demo already exists; use a clean workspace for this verification"
        )

    def run(arguments, expected):
        completed = subprocess.run(
            [sys.executable, "-m", "evaluation_lab", *arguments], check=False
        )
        if completed.returncode != expected:
            raise SystemExit(f"Expected exit {expected}, received {completed.returncode}")

    run(["run", "--dataset", "datasets/demo.jsonl", "--output", str(base / "baseline")], 0)
    run(
        [
            "run",
            "--dataset",
            "datasets/demo.jsonl",
            "--target",
            "evaluation_lab.targets:flawed",
            "--output",
            str(base / "candidate"),
        ],
        1,
    )
    run(
        [
            "compare",
            "--baseline",
            str(base / "baseline/report.json"),
            "--candidate",
            str(base / "candidate/report.json"),
            "--output",
            str(base / "comparison.json"),
        ],
        1,
    )
    baseline = json.loads((base / "baseline/summary.json").read_text())
    candidate = json.loads((base / "candidate/summary.json").read_text())
    comparison = json.loads((base / "comparison.json").read_text())
    assert baseline["passed"] == 16 and candidate["passed"] == 0
    assert comparison["regressions"] and not comparison["passed"]
    print(
        "Verified: good target passes, flawed target fails, regression gate catches deterioration."
    )


if __name__ == "__main__":
    main()
