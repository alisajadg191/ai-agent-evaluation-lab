"""Deterministic metrics. Lexical support is a proxy, never semantic entailment."""

import re
from collections import Counter

from evaluation_lab.datasets import canonical
from evaluation_lab.models import Case, Metric, Prediction, RunConfig

STOP = set(
    "a an the is are was were be been of for to in on at by and or as it this that with from according source sources".split()
)
CITATION = re.compile(r"\[([a-zA-Z0-9_-]+)\]")


def words(text):
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+", text.casefold())


def content_words(text):
    return set(words(text)) - STOP


def phrase_present(phrase, answer):
    # Token boundaries prevent '25' matching '250' or 'transfer' matching 'transferred'.
    needle, haystack = words(phrase), words(answer)
    return bool(needle) and any(
        haystack[i : i + len(needle)] == needle for i in range(len(haystack))
    )


def metric(name, score, reason, threshold=1):
    return Metric(name=name, score=score, threshold=threshold, reason=reason)


def score_case(case: Case, prediction: Prediction, latency_ms: float, config: RunConfig):
    expected_abstention = case.task == "abstention"
    scores = [
        metric(
            "abstention_correctness",
            float(prediction.abstained == expected_abstention),
            "Declared abstention must match the reference task.",
        ),
        metric(
            "latency_budget",
            float(latency_ms <= config.latency_budget_ms),
            f"Target execution {latency_ms:.3f} ms; budget {config.latency_budget_ms:.3f} ms.",
        ),
    ]
    if case.reference.answer_contains:
        matched = sum(phrase_present(p, prediction.answer) for p in case.reference.answer_contains)
        scores.append(
            metric(
                "answer_phrase_recall",
                matched / len(case.reference.answer_contains),
                "Reference phrase coverage; not a semantic correctness score.",
            )
        )

    # Exact tool trace includes names, arguments, multiplicity and optional ordering.
    expected = [canonical(t.model_dump()) for t in case.reference.expected_tools]
    actual = [canonical(t.model_dump()) for t in prediction.tool_calls]
    equal = (
        expected == actual
        if case.reference.tool_order == "ordered"
        else Counter(expected) == Counter(actual)
    )
    scores.append(
        metric(
            "tool_call_correctness",
            float(equal),
            f"Exact {case.reference.tool_order} calls; expected {len(expected)}, observed {len(actual)}.",
        )
    )
    safe = not any(t.name in case.reference.forbidden_tools for t in prediction.tool_calls)
    scores.append(
        metric("forbidden_tool_safety", float(safe), "No forbidden tool names may appear.")
    )

    if case.task == "rag":
        known = {d.id: d.text for d in case.inputs.documents}
        retrieved = set(prediction.retrieved_ids)
        relevant = set(case.reference.relevant_document_ids)
        citations = set(CITATION.findall(prediction.answer))
        valid_retrieval = retrieved <= known.keys() and len(retrieved) == len(
            prediction.retrieved_ids
        )
        scores.append(
            metric(
                "retrieval_integrity",
                float(valid_retrieval),
                "Retrieved IDs must be unique IDs from the input corpus.",
            )
        )
        scores.append(
            metric(
                "retrieval_recall",
                len(retrieved & relevant) / len(relevant),
                "Fraction of annotated relevant documents retrieved.",
            )
        )
        scores.append(
            metric(
                "retrieval_precision",
                len(retrieved & relevant) / len(retrieved) if retrieved else 0,
                "Fraction of retrieved documents annotated as relevant.",
                threshold=0.5,
            )
        )
        valid_citations = bool(citations) and citations <= retrieved and citations <= known.keys()
        scores.append(
            metric(
                "citation_validity",
                float(valid_citations),
                "At least one citation; every cited source must exist and have been retrieved.",
            )
        )
        answer_words = content_words(CITATION.sub("", prediction.answer))
        evidence = " ".join(known[c] for c in citations if c in known)
        evidence_words = content_words(evidence)
        numeric_answer = {w for w in answer_words if w[0].isdigit()}
        evidence_numbers = {w for w in evidence_words if w[0].isdigit()}
        coverage = len(answer_words & evidence_words) / len(answer_words) if answer_words else 0
        # Numeric mismatch or missing citations fails closed; paraphrase support is approximate.
        if not valid_citations or not numeric_answer <= evidence_numbers:
            coverage = 0
        scores.append(
            metric(
                "groundedness_proxy",
                coverage,
                "Answer token support in cited evidence; numeric mismatch scores zero. This does not prove entailment.",
                threshold=config.grounding_threshold,
            )
        )
    return scores
