"""Tests for promptpolygraph.redteam.converters.

All converters are pure functions with no LLM or network dependency, so these
tests run fully offline.
"""

from __future__ import annotations

import base64 as _b64

import pytest

from promptpolygraph.redteam.converters import (
    apply,
    apply_chain,
    base64,
    leetspeak,
    list_converters,
    many_shot,
    payload_split,
    reverse,
    rot13,
)


# ---------------------------------------------------------------------------
# base64
# ---------------------------------------------------------------------------


def test_base64_round_trip():
    """The base64 token embedded in the output must decode back to the original."""
    original = "test probe string"
    result = base64(original)
    # The encoded token is the last whitespace-separated word before the
    # instruction text ends.  We extract any b64-looking token.
    import re

    # base64 tokens contain only [A-Za-z0-9+/=]
    tokens = re.findall(r"[A-Za-z0-9+/=]{4,}", result)
    decoded = None
    for tok in tokens:
        try:
            candidate = _b64.b64decode(tok + "==").decode()
            if original in candidate or candidate.strip() == original.strip():
                decoded = candidate
                break
        except Exception:
            continue
    assert decoded is not None, f"Could not recover original from: {result!r}"
    assert original in decoded


# ---------------------------------------------------------------------------
# rot13
# ---------------------------------------------------------------------------


def test_rot13_double_is_identity():
    text = "Hello, World! 123"
    assert rot13(rot13(text)) == text


def test_rot13_actually_changes_letters():
    assert rot13("abc") != "abc"


# ---------------------------------------------------------------------------
# leetspeak
# ---------------------------------------------------------------------------


def test_leetspeak_contains_digits():
    result = leetspeak("test")
    assert any(ch.isdigit() for ch in result), f"No digits in {result!r}"


def test_leetspeak_known_substitutions():
    assert "4" in leetspeak("apple")
    assert "3" in leetspeak("bee")
    assert "0" in leetspeak("dog")


# ---------------------------------------------------------------------------
# reverse
# ---------------------------------------------------------------------------


def test_reverse_double_is_identity():
    text = "abcdefg 123"
    assert reverse(reverse(text)) == text


def test_reverse_changes_non_palindrome():
    assert reverse("hello") != "hello"


# ---------------------------------------------------------------------------
# payload_split
# ---------------------------------------------------------------------------


def test_payload_split_contains_both_halves():
    text = "abcdefgh"
    result = payload_split(text)
    # First half: "abcd", second half: "efgh"
    assert "abcd" in result
    assert "efgh" in result


def test_payload_split_short_input():
    # Even a two-char input should not crash.
    result = payload_split("ab")
    assert "a" in result and "b" in result


# ---------------------------------------------------------------------------
# many_shot
# ---------------------------------------------------------------------------


def test_many_shot_contains_final_text():
    result = many_shot("final request", n=5)
    assert "final request" in result


def test_many_shot_has_enough_example_markers():
    """At least n 'User:' lines must appear before the final turn."""
    n = 5
    result = many_shot("final request", n=n)
    # n example turns + 1 real turn = n+1 'User:' occurrences minimum
    user_count = result.count("User:")
    assert user_count >= n, f"Expected ≥{n} example markers, found {user_count}"


def test_many_shot_default_n():
    result = many_shot("ping")
    assert result.count("User:") >= 8


def test_many_shot_custom_examples():
    examples = [("Q1", "A1"), ("Q2", "A2")]
    result = many_shot("real", n=3, examples=examples)
    assert "real" in result
    assert result.count("User:") >= 3


def test_many_shot_empty_examples_raises():
    with pytest.raises(ValueError):
        many_shot("x", n=1, examples=[])


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def test_list_converters_non_empty():
    names = list_converters()
    assert len(names) > 0


def test_list_converters_includes_all_expected():
    names = set(list_converters())
    expected = {
        "base64", "rot13", "leetspeak", "reverse",
        "unicode_confusable", "payload_split", "roleplay_wrap", "whitespace_pad",
    }
    assert expected.issubset(names), f"Missing: {expected - names}"


def test_apply_rot13_works():
    result = apply("rot13", "abc")
    assert result == rot13("abc")


def test_apply_unknown_raises_key_error():
    with pytest.raises(KeyError, match="nope"):
        apply("nope", "x")


def test_apply_chain_runs_and_differs():
    original = "test"
    result = apply_chain(["leetspeak", "reverse"], original)
    assert isinstance(result, str)
    assert result != original


def test_apply_chain_empty_is_identity():
    text = "unchanged"
    assert apply_chain([], text) == text


def test_apply_chain_unknown_raises():
    with pytest.raises(KeyError):
        apply_chain(["rot13", "nonexistent"], "hi")


# ---------------------------------------------------------------------------
# CONVERTER_STRATEGY metadata
# ---------------------------------------------------------------------------


def test_converter_strategy_covers_all_registry_entries():
    from promptpolygraph.redteam.converters import CONVERTER_STRATEGY, CONVERTERS

    for name in CONVERTERS:
        assert name in CONVERTER_STRATEGY, f"{name!r} missing from CONVERTER_STRATEGY"


def test_converter_strategy_values_are_valid():
    from promptpolygraph.redteam.converters import CONVERTER_STRATEGY

    valid = {"obfuscation", "jailbreak"}
    for name, strategy in CONVERTER_STRATEGY.items():
        assert strategy in valid, f"{name!r} has unexpected strategy {strategy!r}"


def test_roleplay_wrap_and_many_shot_are_jailbreak():
    from promptpolygraph.redteam.converters import CONVERTER_STRATEGY

    assert CONVERTER_STRATEGY["roleplay_wrap"] == "jailbreak"
    assert CONVERTER_STRATEGY["many_shot"] == "jailbreak"
