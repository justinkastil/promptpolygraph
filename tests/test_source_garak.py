"""Tests for the GarakSource attack source.

All tests run in mock mode so they work without the optional ``garak`` package.
The ``asyncio_mode = "auto"`` pytest-asyncio setting in pyproject.toml means no
explicit marker is needed — async test functions are picked up automatically.
"""

from __future__ import annotations

import pytest

from promptpolygraph.redteam.sources import get_source, list_sources
from promptpolygraph.redteam.sources.base import GeneratedProbe
from promptpolygraph.redteam.sources.garak_source import (
    GarakSource,
    _ALL_STRATEGIES,
    _static_probes,
    make_garak_source,
)


# ---------------------------------------------------------------------------
# Factory and registration
# ---------------------------------------------------------------------------


def test_make_garak_source_returns_correct_name():
    source = make_garak_source()
    assert source.name == "garak"


def test_make_garak_source_has_available_method():
    source = make_garak_source()
    assert callable(source.available)
    # available() must return a bool without raising
    result = source.available()
    assert isinstance(result, bool)


def test_garak_appears_in_list_sources():
    assert "garak" in list_sources()


def test_get_source_garak_returns_garak_source():
    source = get_source("garak")
    assert source.name == "garak"
    assert isinstance(source, GarakSource)


# ---------------------------------------------------------------------------
# Static probes helper
# ---------------------------------------------------------------------------


def test_static_probes_all_strategies_when_empty():
    probes = _static_probes([])
    strategies_seen = {p.strategy for p in probes}
    # All seven families should be represented in the static set.
    assert strategies_seen == set(_ALL_STRATEGIES)


def test_static_probes_filters_to_requested():
    probes = _static_probes(["jailbreak", "obfuscation"])
    for p in probes:
        assert p.strategy in {"jailbreak", "obfuscation"}
    strategies_seen = {p.strategy for p in probes}
    assert "jailbreak" in strategies_seen
    assert "obfuscation" in strategies_seen


def test_static_probes_are_well_formed():
    probes = _static_probes(list(_ALL_STRATEGIES))
    for p in probes:
        assert isinstance(p, GeneratedProbe)
        assert p.source == "garak"
        assert isinstance(p.prompt, str) and p.prompt.strip()
        assert p.strategy in set(_ALL_STRATEGIES)
        assert p.technique is not None and p.technique.startswith("garak:")


# ---------------------------------------------------------------------------
# generate() — mock path
# ---------------------------------------------------------------------------


async def test_generate_mock_filtered_strategies_returns_correct_subset():
    source = make_garak_source()
    probes = await source.generate(
        target_desc=None,
        count=6,
        strategies=["jailbreak", "obfuscation"],
        mock=True,
    )
    # count respected
    assert len(probes) <= 6
    # all probes have the right source
    for p in probes:
        assert p.source == "garak"
    # all probes belong to the requested strategies
    for p in probes:
        assert p.strategy in {"jailbreak", "obfuscation"}
    # prompts are non-empty strings
    for p in probes:
        assert isinstance(p.prompt, str) and p.prompt.strip()


async def test_generate_mock_empty_strategies_covers_multiple_families():
    source = make_garak_source()
    probes = await source.generate(
        target_desc=None,
        count=100,
        strategies=[],
        mock=True,
    )
    strategies_seen = {p.strategy for p in probes}
    # With an empty strategy filter and a generous count, we should see more
    # than one family (the static set covers all seven).
    assert len(strategies_seen) > 1


async def test_generate_mock_source_field_is_garak():
    source = make_garak_source()
    probes = await source.generate(
        target_desc="a generic chatbot for testing",
        count=10,
        strategies=["prompt_injection", "system_prompt_leak"],
        mock=True,
    )
    for p in probes:
        assert p.source == "garak"


async def test_generate_mock_respects_count():
    source = make_garak_source()
    probes = await source.generate(
        target_desc=None,
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    assert len(probes) <= 3


async def test_generate_mock_returns_generated_probe_instances():
    source = make_garak_source()
    probes = await source.generate(
        target_desc=None,
        count=4,
        strategies=["obfuscation"],
        mock=True,
    )
    for p in probes:
        assert isinstance(p, GeneratedProbe)


async def test_generate_mock_count_zero_returns_all():
    """count=0 is interpreted as 'return all available' (no cap)."""
    source = make_garak_source()
    probes = await source.generate(
        target_desc=None,
        count=0,
        strategies=["jailbreak"],
        mock=True,
    )
    # Should return at least the 2 static jailbreak entries.
    assert len(probes) >= 2
    for p in probes:
        assert p.strategy == "jailbreak"


# ---------------------------------------------------------------------------
# available() with garak absent
# ---------------------------------------------------------------------------


def test_available_returns_false_when_garak_missing(monkeypatch):
    """When garak is not installed, available() should return False."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "garak" or name.startswith("garak."):
            raise ImportError("garak not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    source = GarakSource()
    assert source.available() is False


async def test_generate_falls_back_to_static_when_garak_missing(monkeypatch):
    """When garak cannot be imported, generate() returns static probes regardless
    of mock flag."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "garak" or name.startswith("garak."):
            raise ImportError("garak not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    source = GarakSource()
    # mock=False but garak unavailable — should still return probes
    probes = await source.generate(
        target_desc=None,
        count=10,
        strategies=["jailbreak"],
        mock=False,
    )
    assert len(probes) > 0
    for p in probes:
        assert p.source == "garak"
        assert p.strategy == "jailbreak"
