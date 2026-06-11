"""Tests for the PyRIT attack source (``promptpolygraph.redteam.sources.pyrit_source``).

All assertions run in mock mode so the test suite requires no optional deps.
``asyncio_mode = "auto"`` is set in pyproject.toml so async test functions
are discovered and awaited automatically by pytest-asyncio.
"""

from __future__ import annotations

import pytest

from promptpolygraph.redteam.sources import get_source, list_sources
from promptpolygraph.redteam.sources.base import GeneratedProbe
from promptpolygraph.redteam.sources.pyrit_source import (
    PyRITSource,
    _ALL_STRATEGIES,
    _static_probes,
    make_pyrit_source,
)


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_pyrit_is_registered():
    """``pyrit`` must appear in the source registry after module import."""
    assert "pyrit" in list_sources()


def test_get_source_returns_pyrit_instance():
    src = get_source("pyrit")
    assert src.name == "pyrit"
    assert isinstance(src, PyRITSource)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_make_pyrit_source_factory():
    src = make_pyrit_source()
    assert src.name == "pyrit"
    # available() is a bool — just assert it doesn't raise
    result = src.available()
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Static-probe helper
# ---------------------------------------------------------------------------


def test_static_probes_returns_probes_for_known_strategy():
    probes = _static_probes(["jailbreak"])
    assert probes, "expected at least one static probe for 'jailbreak'"
    for p in probes:
        assert isinstance(p, GeneratedProbe)
        assert p.strategy == "jailbreak"
        assert p.source == "pyrit"
        assert p.prompt.strip()
        assert p.technique and p.technique.startswith("pyrit:")


def test_static_probes_filters_to_requested_strategies():
    probes = _static_probes(["obfuscation", "jailbreak"])
    strategies_present = {p.strategy for p in probes}
    assert strategies_present <= {"obfuscation", "jailbreak"}


def test_static_probes_empty_on_unknown_strategy():
    probes = _static_probes(["nonexistent_strategy_xyz"])
    assert probes == []


# ---------------------------------------------------------------------------
# generate() — mock path (the primary exercisable path in CI)
# ---------------------------------------------------------------------------


async def test_generate_mock_returns_probes_within_count():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc="a generic assistant",
        count=6,
        strategies=["obfuscation", "jailbreak"],
        mock=True,
    )
    assert len(probes) <= 6
    assert probes, "expected at least one probe"


async def test_generate_mock_probes_have_correct_source():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc="a generic assistant",
        count=6,
        strategies=["obfuscation", "jailbreak"],
        mock=True,
    )
    for p in probes:
        assert p.source == "pyrit", f"unexpected source: {p.source!r}"


async def test_generate_mock_strategies_restricted_to_requested():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc="a generic assistant",
        count=6,
        strategies=["obfuscation", "jailbreak"],
        mock=True,
    )
    for p in probes:
        assert p.strategy in {"obfuscation", "jailbreak"}, (
            f"strategy {p.strategy!r} outside requested set"
        )


async def test_generate_mock_prompts_are_non_empty():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc="a generic assistant",
        count=6,
        strategies=["obfuscation", "jailbreak"],
        mock=True,
    )
    for p in probes:
        assert p.prompt.strip(), "probe prompt must not be blank"


async def test_generate_mock_techniques_prefixed_pyrit():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc="a generic assistant",
        count=10,
        strategies=["obfuscation", "jailbreak"],
        mock=True,
    )
    for p in probes:
        assert p.technique is not None, "technique must be set"
        assert p.technique.startswith("pyrit:"), (
            f"technique {p.technique!r} does not start with 'pyrit:'"
        )


# ---------------------------------------------------------------------------
# generate() — empty strategies list → all strategies returned
# ---------------------------------------------------------------------------


async def test_generate_mock_empty_strategies_covers_all():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc=None,
        count=100,
        strategies=[],
        mock=True,
    )
    assert probes, "expected probes when strategies=[]"
    strats_returned = {p.strategy for p in probes}
    # At least several distinct strategies should appear
    assert len(strats_returned) >= 3, (
        f"expected multiple strategies; got {strats_returned}"
    )
    # All returned strategies must be valid
    for s in strats_returned:
        assert s in _ALL_STRATEGIES, f"unknown strategy {s!r} in output"


async def test_generate_mock_none_target_desc_does_not_raise():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc=None,
        count=4,
        strategies=["prompt_injection"],
        mock=True,
    )
    assert isinstance(probes, list)


# ---------------------------------------------------------------------------
# generate() — count=0 means "no cap" (return all static probes)
# ---------------------------------------------------------------------------


async def test_generate_mock_zero_count_returns_all():
    src = make_pyrit_source()
    probes = await src.generate(
        target_desc=None,
        count=0,
        strategies=["system_prompt_leak", "pii_extraction"],
        mock=True,
    )
    assert probes, "expected probes when count=0"


# ---------------------------------------------------------------------------
# available() contract
# ---------------------------------------------------------------------------


def test_available_returns_bool():
    src = make_pyrit_source()
    assert isinstance(src.available(), bool)


# ---------------------------------------------------------------------------
# GeneratedProbe dataclass sanity
# ---------------------------------------------------------------------------


def test_generated_probe_fields():
    p = GeneratedProbe(
        strategy="obfuscation",
        prompt="test probe",
        source="pyrit",
        technique="pyrit:base64_encoded",
    )
    assert p.strategy == "obfuscation"
    assert p.prompt == "test probe"
    assert p.source == "pyrit"
    assert p.technique == "pyrit:base64_encoded"
