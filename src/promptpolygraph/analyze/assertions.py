"""Deterministic, code-checkable assertions over a response.

These run before any LLM judge and are cheap. Every spec is evaluated
defensively: a malformed spec produces a failed `AssertionResult` rather than
raising, so one bad probe can never abort a batch.
"""

from __future__ import annotations

import json
import re

from ..models import AssertionResult, AssertionSpec, Case, Response


def _re_flags(flags: str) -> int:
    out = 0
    if "i" in flags:
        out |= re.IGNORECASE
    if "m" in flags:
        out |= re.MULTILINE
    if "s" in flags:
        out |= re.DOTALL
    return out


def _eval_one(spec: AssertionSpec, resp: Response) -> AssertionResult:
    kind = spec.kind
    value = spec.value
    text = resp.text or ""
    desc = spec.description

    def ok(passed: bool, detail: str = "") -> AssertionResult:
        return AssertionResult(kind=kind, passed=passed, description=desc, detail=detail)

    try:
        if kind == "contains":
            needle = str(value)
            if "i" in spec.flags:
                passed = needle.lower() in text.lower()
            else:
                passed = needle in text
            return ok(passed, "" if passed else f"missing substring: {needle!r}")

        if kind == "not_contains":
            needle = str(value)
            if "i" in spec.flags:
                passed = needle.lower() not in text.lower()
            else:
                passed = needle not in text
            return ok(passed, "" if passed else f"forbidden substring present: {needle!r}")

        if kind == "regex":
            passed = re.search(str(value), text, _re_flags(spec.flags)) is not None
            return ok(passed, "" if passed else f"pattern did not match: {value!r}")

        if kind == "not_regex":
            passed = re.search(str(value), text, _re_flags(spec.flags)) is None
            return ok(passed, "" if passed else f"forbidden pattern matched: {value!r}")

        if kind == "equals":
            passed = text == str(value)
            return ok(passed, "" if passed else "text != expected value")

        if kind == "json_valid":
            json.loads(text)
            return ok(True)

        if kind == "json_schema":
            import jsonschema

            obj = json.loads(text)
            jsonschema.validate(instance=obj, schema=value)
            return ok(True)

        if kind == "min_length":
            n = int(value)
            passed = len(text) >= n
            return ok(passed, "" if passed else f"len {len(text)} < {n}")

        if kind == "max_length":
            n = int(value)
            passed = len(text) <= n
            return ok(passed, "" if passed else f"len {len(text)} > {n}")

        if kind == "max_latency_ms":
            n = float(value)
            lat = resp.latency_ms
            if lat is None:
                return ok(False, "no latency recorded")
            passed = lat <= n
            return ok(passed, "" if passed else f"latency {lat}ms > {n}ms")

        if kind == "no_error":
            passed = resp.error is None
            return ok(passed, "" if passed else f"error: {resp.error}")

        return ok(False, f"unknown assertion kind: {kind!r}")
    except Exception as exc:  # noqa: BLE001 - defensive: never raise to the batch
        return ok(False, f"assertion error: {exc}")


def evaluate_assertions(case: Case, resp: Response) -> tuple[list[AssertionResult], bool]:
    """Run every assertion spec on the case; return (results, all_passed)."""
    results = [_eval_one(spec, resp) for spec in case.assertions]
    all_passed = all(r.passed for r in results)
    return results, all_passed
