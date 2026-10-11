import importlib
import multiprocessing
import os
import re
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from uuid import uuid4

from evaluation_lab.datasets import dataset_digest, scoring_digest
from evaluation_lab.judge import judge_grounding
from evaluation_lab.metrics import score_case
from evaluation_lab.models import CaseResult, Prediction, Report, RunConfig


def load_target(spec):
    if not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*:[a-zA-Z_]\w*", spec):
        raise ValueError("Target must use module:function syntax")
    module, name = spec.split(":")
    target = getattr(importlib.import_module(module), name)
    if not callable(target):
        raise ValueError("Target must be callable")
    return target


def _worker(connection, target_spec, inputs):
    # A trusted adapter runs in a disposable process. This is NOT an OS security sandbox.
    try:
        from langsmith import tracing_context

        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            with tracing_context(enabled=False):
                target = load_target(target_spec)
                start = time.perf_counter()
                raw = target(inputs)
                latency = (time.perf_counter() - start) * 1000
                prediction = Prediction.model_validate(raw)
        connection.send(
            {
                "status": "ok",
                "prediction": prediction.model_dump(mode="json"),
                "latency_ms": latency,
            }
        )
    except BaseException as exc:
        connection.send({"status": "error", "error_type": type(exc).__name__})
    finally:
        connection.close()


def execute_target(spec, inputs, timeout_seconds):
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sending, spec, inputs))
    start = time.perf_counter()
    process.start()
    sending.close()
    try:
        if receiving.poll(timeout_seconds):
            try:
                result = receiving.recv()
            except EOFError:
                result = {"status": "error", "error_type": "WorkerExited"}
        else:
            result = {"status": "timeout", "error_type": "TargetTimeout"}
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        receiving.close()
    return {**result, "wall_ms": (time.perf_counter() - start) * 1000}


def run_evaluation(cases, config: RunConfig):
    results, events = [], []
    run_id = str(uuid4())
    for case in cases:
        for repetition in range(config.repetitions):
            execution = execute_target(
                config.target, case.inputs.model_dump(mode="json"), config.timeout_seconds
            )
            row = CaseResult(case_id=case.id, repetition=repetition, **execution)
            events.append(
                {
                    "run_id": run_id,
                    "case_id": case.id,
                    "repetition": repetition,
                    "event": "target.complete",
                    "status": row.status,
                    "latency_ms": row.latency_ms,
                    "wall_ms": row.wall_ms,
                    "error_type": row.error_type,
                }
            )
            start = time.perf_counter()
            if row.prediction is not None:
                row.metrics = score_case(case, row.prediction, row.latency_ms, config)
                if config.judge_model and case.task == "rag":
                    row.metrics.append(judge_grounding(case, row.prediction, config))
            events.append(
                {
                    "run_id": run_id,
                    "case_id": case.id,
                    "repetition": repetition,
                    "event": "evaluation.complete",
                    "duration_ms": (time.perf_counter() - start) * 1000,
                    "passed": row.passed,
                    "metrics": {m.name: m.score for m in row.metrics},
                }
            )
            results.append(row)
    return Report(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        dataset_sha256=dataset_digest(cases),
        scoring_sha256=scoring_digest(config),
        config=config,
        cases=cases,
        results=results,
    ), events
