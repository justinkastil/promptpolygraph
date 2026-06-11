"""Tests for the Llama-Guard-style breach judge (guard.py).

All tests run in mock mode — no network calls, no API keys required.
asyncio_mode = "auto" is set in pyproject.toml so async test functions are
collected and run automatically.
"""

from __future__ import annotations

import pytest

from promptpolygraph.redteam.guard import (
    _HAZARD_MAP,
    _parse_guard_output,
    llama_guard_verdict,
    make_guard_judge,
)
from promptpolygraph.redteam.models import AttackAttempt, BreachVerdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attempt(response: str = "", strategy: str = "jailbreak") -> AttackAttempt:
    return AttackAttempt(attacker_id="x", strategy=strategy, prompt="p", response=response)


# ---------------------------------------------------------------------------
# llama_guard_verdict — mock path
# ---------------------------------------------------------------------------


async def test_empty_response_is_breached():
    """An empty target response is treated as a guardrail failure."""
    attempt = AttackAttempt(attacker_id="x", strategy="jailbreak", prompt="p", response="")
    verdict = await llama_guard_verdict(None, attempt, mock=True)
    assert isinstance(verdict, BreachVerdict)
    assert verdict.breached is True
    assert verdict.severity in {"low", "medium", "high", "critical"}


async def test_benign_refusal_returns_valid_verdict():
    """A clean refusal response returns a valid BreachVerdict; breached is a bool."""
    attempt = _attempt(response="I'm sorry, I can't help with that.")
    verdict = await llama_guard_verdict(None, attempt, mock=True)
    assert isinstance(verdict, BreachVerdict)
    assert isinstance(verdict.breached, bool)
    assert verdict.severity in {"none", "low", "medium", "high", "critical"}


async def test_none_client_forces_mock():
    """Passing client=None always produces a mock verdict without raising."""
    attempt = _attempt(response="some normal response")
    verdict = await llama_guard_verdict(None, attempt)
    assert isinstance(verdict, BreachVerdict)


async def test_breach_markers_trigger_breach():
    """Responses containing 'breach' or 'system prompt' are always flagged."""
    for resp in ("Here is the breach data.", "I will reveal the system prompt now."):
        verdict = await llama_guard_verdict(None, _attempt(response=resp), mock=True)
        assert verdict.breached is True, f"expected breach for: {resp!r}"


async def test_verdict_fields_always_populated():
    """Every BreachVerdict must have non-None required fields."""
    attempt = _attempt(response="Totally fine response with no issues.")
    verdict = await llama_guard_verdict(None, attempt, mock=True)
    assert verdict.severity is not None
    assert verdict.vuln_class is not None
    assert verdict.rationale is not None


# ---------------------------------------------------------------------------
# make_guard_judge — factory
# ---------------------------------------------------------------------------


async def test_make_guard_judge_returns_callable():
    """make_guard_judge() returns an async callable."""
    judge = make_guard_judge()
    assert callable(judge)


async def test_guard_judge_mock_returns_breach_verdict():
    """The factory judge returns a BreachVerdict in mock mode."""
    judge = make_guard_judge()
    attempt = AttackAttempt(attacker_id="x", strategy="jailbreak", prompt="p", response="I cannot help")
    verdict = await judge(attempt, mock=True)
    assert isinstance(verdict, BreachVerdict)
    assert isinstance(verdict.breached, bool)


async def test_guard_judge_mock_does_not_build_client(monkeypatch):
    """In mock mode the factory must never call make_client (no network/key needed)."""
    called: list[str] = []

    def _fake_make_client(*args, **kwargs):  # noqa: ANN001
        called.append("make_client")
        raise RuntimeError("should not build a client in mock mode")

    monkeypatch.setattr("promptpolygraph.redteam.guard.make_client", _fake_make_client)

    judge = make_guard_judge()
    attempt = AttackAttempt(attacker_id="x", strategy="jailbreak", prompt="p", response="")
    verdict = await judge(attempt, mock=True)
    assert isinstance(verdict, BreachVerdict)
    assert called == [], "make_client was called during mock mode — it should not be"


async def test_guard_judge_different_strategies():
    """The judge works regardless of the strategy field value."""
    judge = make_guard_judge(model="llama-guard3")
    for strategy in ("jailbreak", "prompt_injection", "pii_extraction", "obfuscation"):
        attempt = AttackAttempt(attacker_id="a", strategy=strategy, prompt="q", response="ok")
        verdict = await judge(attempt, mock=True)
        assert isinstance(verdict, BreachVerdict)


# ---------------------------------------------------------------------------
# _parse_guard_output — unit tests
# ---------------------------------------------------------------------------


def test_parse_safe():
    is_unsafe, codes = _parse_guard_output("safe")
    assert is_unsafe is False
    assert codes == []


def test_parse_unsafe_with_codes():
    is_unsafe, codes = _parse_guard_output("unsafe\nS1,S6")
    assert is_unsafe is True
    assert "S1" in codes
    assert "S6" in codes


def test_parse_unsafe_no_codes():
    is_unsafe, codes = _parse_guard_output("unsafe")
    assert is_unsafe is True
    assert codes == []


def test_parse_blank_input():
    is_unsafe, codes = _parse_guard_output("")
    assert is_unsafe is False
    assert codes == []


def test_parse_case_insensitive():
    is_unsafe, _ = _parse_guard_output("UNSAFE\nS2")
    assert is_unsafe is True


# ---------------------------------------------------------------------------
# Hazard map integrity
# ---------------------------------------------------------------------------


def test_hazard_map_covers_s1_to_s14():
    """All S1-S14 codes must be present in the hazard map."""
    for i in range(1, 15):
        code = f"S{i}"
        assert code in _HAZARD_MAP, f"missing hazard code {code}"


def test_hazard_map_severities_are_valid():
    valid = {"none", "low", "medium", "high", "critical"}
    for code, (vuln_class, severity) in _HAZARD_MAP.items():
        assert severity in valid, f"{code}: invalid severity {severity!r}"
        assert vuln_class, f"{code}: vuln_class must not be empty"


# ---------------------------------------------------------------------------
# Live path with ScriptedClient
# ---------------------------------------------------------------------------


async def test_live_safe_response():
    """A scripted 'safe' reply produces breached=False."""
    from promptpolygraph.llm import ScriptedClient

    client = ScriptedClient(["safe"])
    verdict = await llama_guard_verdict(client, _attempt(response="The answer is 42."))
    assert verdict.breached is False
    assert verdict.severity == "none"


async def test_live_unsafe_response_maps_hazard():
    """A scripted 'unsafe\\nS7' reply maps to the privacy_violation vuln_class."""
    from promptpolygraph.llm import ScriptedClient

    client = ScriptedClient(["unsafe\nS7"])
    verdict = await llama_guard_verdict(client, _attempt(response="Here is your private data."))
    assert verdict.breached is True
    assert verdict.vuln_class == "privacy_violation"
    assert verdict.severity == "high"


async def test_live_unknown_hazard_code_uses_fallback():
    """An unrecognised code (e.g. S99) falls back to 'unknown_hazard'."""
    from promptpolygraph.llm import ScriptedClient

    client = ScriptedClient(["unsafe\nS99"])
    verdict = await llama_guard_verdict(client, _attempt(response="weird output"))
    assert verdict.breached is True
    assert verdict.vuln_class == "unknown_hazard"


async def test_live_parse_error_falls_back_to_mock():
    """A malformed classifier response triggers the mock fallback without raising."""
    from promptpolygraph.llm import ScriptedClient

    client = ScriptedClient(["THIS IS NOT VALID OUTPUT !!!"])
    attempt = _attempt(response="some response")
    verdict = await llama_guard_verdict(client, attempt)
    # Should degrade gracefully — still returns a valid BreachVerdict.
    assert isinstance(verdict, BreachVerdict)
