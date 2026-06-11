"""Tests for the multi-turn red-team probe generators (PAIR, Crescendo, TAP).

All tests run in mock mode (client=None, mock=True) so no LLM key is required.
pytest-asyncio asyncio_mode=auto (configured in pyproject.toml) means ordinary
``async def`` test functions are collected and awaited automatically.
"""

from __future__ import annotations

import pytest

from promptpolygraph.redteam.multiturn import (
    MULTITURN,
    crescendo_next,
    list_multiturn,
    pair_next,
    tap_candidates,
)


# ---------------------------------------------------------------------------
# PAIR
# ---------------------------------------------------------------------------


async def test_pair_next_returns_nonempty_and_differs_from_prior_probe():
    prior_probe = "p"
    prior_response = "I can't help with that"
    history = [{"prompt": prior_probe, "response": prior_response, "breached": False}]
    result = await pair_next(
        None,
        strategy="jailbreak",
        target_desc=None,
        history=history,
        mock=True,
    )
    assert isinstance(result, str)
    assert result, "pair_next must return a non-empty string"
    assert result != prior_probe, "PAIR refine must differ from the original probe"


async def test_pair_next_empty_history_returns_nonempty():
    result = await pair_next(
        None,
        strategy="jailbreak",
        target_desc=None,
        history=[],
        mock=True,
    )
    assert isinstance(result, str)
    assert result


async def test_pair_next_refusal_text_referenced_in_output():
    """The mock path should include a snippet of the prior response."""
    history = [{"prompt": "first probe", "response": "I can't help with that", "breached": False}]
    result = await pair_next(
        None,
        strategy="jailbreak",
        target_desc=None,
        history=history,
        mock=True,
    )
    # The mock string should encode the PAIR iteration concept
    assert "PAIR" in result or "refine" in result or "rephrase" in result or "bypass" in result


# ---------------------------------------------------------------------------
# Crescendo
# ---------------------------------------------------------------------------


async def test_crescendo_next_empty_history_nonempty():
    result = await crescendo_next(
        None,
        strategy="refusal_robustness",
        target_desc=None,
        history=[],
        turns=3,
        mock=True,
    )
    assert isinstance(result, str)
    assert result


async def test_crescendo_next_later_step_differs_from_first_step():
    first = await crescendo_next(
        None,
        strategy="refusal_robustness",
        target_desc=None,
        history=[],
        turns=3,
        mock=True,
    )
    # Simulate two prior turns
    h2 = [
        {"prompt": "turn 1 probe", "response": "ok", "breached": False},
        {"prompt": "turn 2 probe", "response": "still no", "breached": False},
    ]
    later = await crescendo_next(
        None,
        strategy="refusal_robustness",
        target_desc=None,
        history=h2,
        turns=3,
        mock=True,
    )
    assert isinstance(later, str)
    assert later
    assert later != first, "step 3 of 3 should differ from step 1 of 3"


async def test_crescendo_next_phase_labels_reflect_progress():
    """Early vs late step mock strings should mention different phases."""
    early = await crescendo_next(
        None,
        strategy="jailbreak",
        target_desc=None,
        history=[],
        turns=10,
        mock=True,
    )
    late_history = [{"prompt": f"p{i}", "response": "r", "breached": False} for i in range(9)]
    late = await crescendo_next(
        None,
        strategy="jailbreak",
        target_desc=None,
        history=late_history,
        turns=10,
        mock=True,
    )
    # Both non-empty and distinct (phase framing differs)
    assert early and late
    assert early != late


# ---------------------------------------------------------------------------
# TAP
# ---------------------------------------------------------------------------


async def test_tap_candidates_returns_exactly_branching_distinct_nonempty():
    results = await tap_candidates(
        None,
        strategy="prompt_injection",
        target_desc=None,
        history=[],
        branching=3,
        mock=True,
    )
    assert isinstance(results, list)
    assert len(results) == 3, f"expected 3 candidates, got {len(results)}"
    for item in results:
        assert isinstance(item, str) and item, "each candidate must be a non-empty string"
    assert len(set(results)) == 3, "all 3 candidates must be distinct"


async def test_tap_candidates_branching_1():
    results = await tap_candidates(
        None,
        strategy="jailbreak",
        target_desc=None,
        history=[],
        branching=1,
        mock=True,
    )
    assert len(results) == 1
    assert results[0]


async def test_tap_candidates_branching_5():
    results = await tap_candidates(
        None,
        strategy="obfuscation",
        target_desc=None,
        history=[],
        branching=5,
        mock=True,
    )
    assert len(results) == 5
    assert len(set(results)) == 5


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_list_multiturn_contains_pair_and_crescendo():
    names = list_multiturn()
    assert "pair" in names
    assert "crescendo" in names


def test_multiturn_dict_maps_to_callables():
    assert callable(MULTITURN["pair"])
    assert callable(MULTITURN["crescendo"])


def test_list_multiturn_matches_multiturn_keys():
    assert set(list_multiturn()) == set(MULTITURN.keys())
