import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from evaluation_lab.datasets import dataset_digest, load_dataset
from evaluation_lab.langsmith_integration import publish_report
from evaluation_lab.models import RunConfig
from evaluation_lab.regression import compare_reports
from evaluation_lab.reporting import atomic_write, load_report, summarise, write_reports
from evaluation_lab.runner import run_evaluation


def parser():
    root = argparse.ArgumentParser(description="Reproducible RAG and agent evaluations")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="Validate dataset contracts without executing targets"
    )
    validate.add_argument("--dataset", type=Path, required=True)
    run = commands.add_parser("run", help="Execute trusted Python target adapters locally")
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--target", default="evaluation_lab.targets:demo")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--repetitions", type=int, default=1)
    run.add_argument("--timeout", type=float, default=10)
    run.add_argument("--latency-budget-ms", type=float, default=2000)
    run.add_argument("--grounding-threshold", type=float, default=0.8)
    run.add_argument("--judge-model")
    run.add_argument("--judge-url", default=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    run.add_argument("--judge-timeout", type=float, default=30)
    compare = commands.add_parser(
        "compare", help="Compare runs with identical data and evaluator settings"
    )
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--max-score-drop", type=float, default=0)
    compare.add_argument("--max-latency-increase", type=float, default=0.25)
    compare.add_argument("--latency-slack-ms", type=float, default=20)
    publish = commands.add_parser(
        "publish", help="Upload a recorded report and dataset to LangSmith"
    )
    publish.add_argument("--report", type=Path, required=True)
    publish.add_argument("--project-prefix", default="ai-agent-evaluation-lab")
    publish.add_argument(
        "--confirm-upload",
        action="store_true",
        help="Explicitly upload all dataset inputs, references, predictions and scores",
    )
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            cases = load_dataset(args.dataset)
            print(f"Valid dataset: {len(cases)} cases; SHA-256 {dataset_digest(cases)}")
            return 0
        if args.command == "run":
            if args.output.exists() and any(args.output.iterdir()):
                raise ValueError("Output directory is not empty; choose a new run directory")
            cases = load_dataset(args.dataset)
            config = RunConfig(
                target=args.target,
                repetitions=args.repetitions,
                timeout_seconds=args.timeout,
                latency_budget_ms=args.latency_budget_ms,
                grounding_threshold=args.grounding_threshold,
                judge_model=args.judge_model,
                judge_url=args.judge_url,
                judge_timeout_seconds=args.judge_timeout,
            )
            report, events = run_evaluation(cases, config)
            write_reports(report, events, args.output)
            summary = summarise(report)
            print(
                f"Evaluation: {summary['passed']}/{summary['total']} passed; "
                f"errors={summary['errors']}; timeouts={summary['timeouts']}. Reports: {args.output}"
            )
            return 0 if summary["failed"] == 0 else 1
        if args.command == "compare":
            comparison = compare_reports(
                load_report(args.baseline),
                load_report(args.candidate),
                args.max_score_drop,
                args.max_latency_increase,
                args.latency_slack_ms,
            )
            atomic_write(args.output, json.dumps(comparison, indent=2) + "\n")
            print(
                f"Regression gate: {'PASS' if comparison['passed'] else 'FAIL'}; "
                f"{len(comparison['regressions'])} regressions. Report: {args.output}"
            )
            return 0 if comparison["passed"] else 1
        if args.command == "publish":
            if not args.confirm_upload:
                raise ValueError(
                    "Publishing uploads dataset content and predictions. Review the report and pass --confirm-upload"
                )
            result = publish_report(load_report(args.report), args.project_prefix)
            print(json.dumps(result, indent=2))
            return 0
    except ValidationError:
        print(
            "Contract validation failed. Check field types, ranges and required fields.",
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Configuration/dataset failures are distinct from a failing quality gate.
        print(
            f"Configuration error: {type(exc).__name__}. Check paths, contracts and CLI options.",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            f"Operation failed: {type(exc).__name__}. No secret-bearing exception payload was printed.",
            file=sys.stderr,
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
