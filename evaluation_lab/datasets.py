import hashlib
import json
from pathlib import Path

from evaluation_lab.models import SCORER_VERSION, Case, RunConfig


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_dataset(path: Path):
    if path.stat().st_size > 10_000_000:
        raise ValueError("Dataset exceeds the 10 MB limit")
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(Case.model_validate_json(line))
        except ValueError as exc:
            # Avoid echoing potentially sensitive row content from Pydantic's error message.
            raise ValueError(f"Invalid dataset contract at line {number}") from exc
    if not cases or len(cases) > 1000:
        raise ValueError("Dataset must contain 1–1000 cases")
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("Dataset case IDs must be unique")
    return cases


def dataset_digest(cases):
    return digest([c.model_dump(mode="json") for c in sorted(cases, key=lambda c: c.id)])


def scoring_digest(config: RunConfig):
    # Target is intentionally excluded so two implementations can be compared.
    return digest({"scorer": SCORER_VERSION, **config.model_dump(exclude={"target"})})
