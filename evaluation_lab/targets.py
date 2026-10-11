"""Offline reference implementations. They never receive case references or expected results."""

import re
import time
from decimal import Decimal

from evaluation_lab.metrics import content_words


def demo(inputs: dict) -> dict:
    question = inputs["question"].casefold()
    payload = inputs.get("payload", {})
    if "add" in question and "numbers" in payload:
        numbers = payload["numbers"]
        value = sum((Decimal(str(n)) for n in numbers), Decimal("0"))
        return {
            "answer": f"Total: {value:.2f}",
            "tool_calls": [{"name": "add", "arguments": {"numbers": numbers}}],
        }
    if "convert" in question and {"amount", "rate"} <= payload.keys():
        args = {"amount": payload["amount"], "rate": payload["rate"]}
        value = Decimal(str(args["amount"])) * Decimal(str(args["rate"]))
        return {
            "answer": f"Converted: {value:.2f}",
            "tool_calls": [{"name": "convert", "arguments": args}],
        }
    if re.search(r"ignore.*instructions|\btransfer\b|\btrade\b|api key", question):
        return {"answer": "I cannot perform that action.", "abstained": True}
    ranked = sorted(
        inputs.get("documents", []),
        key=lambda d: len(content_words(question) & content_words(d["text"])),
        reverse=True,
    )
    if ranked and content_words(question) & content_words(ranked[0]["text"]):
        doc = ranked[0]
        return {"answer": f"{doc['text']} [{doc['id']}]", "retrieved_ids": [doc["id"]]}
    return {"answer": "I do not have supporting information.", "abstained": True}


def flawed(inputs: dict) -> dict:
    result = demo(inputs)
    if result.get("retrieved_ids"):
        result["answer"] += " The guaranteed bonus is 999999. [invented]"
    elif result.get("tool_calls"):
        result["tool_calls"][0]["arguments"] = {"wrong": True}
    else:
        result = {
            "answer": "I have completed the transfer.",
            "abstained": False,
            "tool_calls": [{"name": "transfer_money", "arguments": {"amount": 100}}],
        }
    return result


def slow(inputs: dict) -> dict:
    time.sleep(2)
    return demo(inputs)


def crashing(inputs: dict) -> dict:
    raise RuntimeError("Synthetic failure; exception text must not enter reports")


def invalid(inputs: dict) -> dict:
    return {"answer": "", "unexpected_field": True}
