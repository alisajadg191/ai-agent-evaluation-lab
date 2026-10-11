"""Adapter for your own HTTP endpoint implementing the Prediction response contract."""

import os

import httpx


def predict(inputs: dict) -> dict:
    endpoint = os.environ["EVAL_TARGET_URL"]
    headers = {}
    if os.getenv("EVAL_TARGET_API_KEY"):
        headers["X-API-Key"] = os.environ["EVAL_TARGET_API_KEY"]
    response = httpx.post(endpoint, json=inputs, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json()
