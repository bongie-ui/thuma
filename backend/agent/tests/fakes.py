"""Scripted stand-ins for the model, for chat and scenario tests."""

import itertools
import json
from unittest import mock

_ids = itertools.count()


def call(name, **arguments):
    return {"id": f"call_{next(_ids)}", "name": name, "arguments": json.dumps(arguments)}


def say(text):
    return {"content": text, "tool_calls": [], "model": "fake"}


def tools(*calls):
    return {"content": "", "tool_calls": list(calls), "model": "fake"}


class ScriptedChat:
    """Each step is a response dict or a callable(messages) -> response dict."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []

    def __call__(self, messages, tool_defs):
        self.seen.append((messages, tool_defs))
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step

    def tool_results(self):
        """Parsed results of every tool message the model was shown."""
        last = self.seen[-1][0]
        return [json.loads(m["content"]) for m in last if m["role"] == "tool"]


def fake_extractor(evidence):
    """Reads test uploads by name: quote@14, quote@10.50, invoice@320, photo:matches."""
    name = evidence.upload.name
    if name.startswith("quote@"):
        evidence.extracted = {"supplier": "Test Supplier", "currency": "USD", "items": [
            {"name": "Cement 50kg bag", "key": "cement_bag", "quantity": 40, "unit_price": float(name[6:])}]}
    elif name.startswith("invoice@"):
        evidence.extracted = {"supplier": "Test School", "total": float(name[8:]), "items": []}
    elif name.startswith("photo:"):
        evidence.extracted = {"verdict": name[6:], "observed": "a concrete slab", "expected": "foundation"}
    evidence.model_name = "fake"
    evidence.save()
    return evidence


def patch_extractor():
    return mock.patch("mandates.services._extract", side_effect=fake_extractor)


def fake_rails():
    """Patch the rail router with a rail that accepts every payout as PENDING. Returns the patcher."""
    from .helpers import fake_pay
    patcher = mock.patch("payments.rails.for_payee")
    for_payee = patcher.start()
    for_payee.return_value.pay.side_effect = fake_pay
    return patcher, for_payee
