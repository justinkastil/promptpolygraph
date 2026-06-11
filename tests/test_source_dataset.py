"""Tests for the DatasetSource attack source.

All tests run in mock mode so they work without the optional ``datasets``
package and without a network connection.

The ``asyncio_mode = "auto"`` setting in pyproject.toml means no explicit
marker is needed — async test functions are discovered and run automatically.
"""

from __future__ import annotations

import pytest

from promptpolygraph.redteam.sources import get_source, list_sources
from promptpolygraph.redteam.sources.base import GeneratedProbe
from promptpolygraph.redteam.sources.dataset_source import (
    DatasetSource,
    _VARIANTS,
    _static_probes,
    make_dataset_source,
)


# ---------------------------------------------------------------------------
# Factory and registration
# ---------------------------------------------------------------------------


def test_make_dataset_source_default_variant():
    """make_dataset_source() with no arguments → name == 'dataset:advbench'."""
    source = make_dataset_source()
    assert source.name == "dataset:advbench"


def test_make_dataset_source_explicit_advbench():
    source = make_dataset_source(variant="advbench")
    assert source.name == "dataset:advbench"


def test_make_dataset_source_harmbench():
    source = make_dataset_source(variant="harmbench")
    assert source.name == "dataset:harmbench"


def test_make_dataset_source_jailbreakbench():
    source = make_dataset_source(variant="jailbreakbench")
    assert source.name == "dataset:jailbreakbench"


def test_make_dataset_source_jbb_alias():
    source = make_dataset_source(variant="jbb")
    assert source.name == "dataset:jbb"


def test_make_dataset_source_none_defaults_to_advbench():
    source = make_dataset_source(variant=None)
    assert source.name == "dataset:advbench"


def test_make_dataset_source_has_available_method():
    source = make_dataset_source(variant="advbench")
    assert callable(source.available)
    result = source.available()
    assert isinstance(result, bool)


def test_dataset_appears_in_list_sources():
    sources = list_sources()
    assert "dataset" in sources


def test_datasets_alias_appears_in_list_sources():
    sources = list_sources()
    assert "datasets" in sources


# ---------------------------------------------------------------------------
# Colon-form resolution via get_source
# ---------------------------------------------------------------------------


def test_get_source_colon_advbench():
    source = get_source("dataset:advbench")
    assert source.name == "dataset:advbench"


def test_get_source_colon_harmbench():
    source = get_source("dataset:harmbench")
    assert source.name == "dataset:harmbench"


def test_get_source_colon_jailbreakbench():
    source = get_source("dataset:jailbreakbench")
    assert source.name == "dataset:jailbreakbench"


def test_get_source_colon_jbb():
    source = get_source("dataset:jbb")
    assert source.name == "dataset:jbb"


def test_get_source_bare_dataset_returns_advbench():
    """Bare 'dataset' name (no colon) uses default variant advbench."""
    source = get_source("dataset")
    assert source.name == "dataset:advbench"


# ---------------------------------------------------------------------------
# _static_probes helper
# ---------------------------------------------------------------------------


def test_static_probes_returns_list_of_generated_probe():
    probes = _static_probes("advbench", ["jailbreak"], 0)
    assert all(isinstance(p, GeneratedProbe) for p in probes)


def test_static_probes_source_field():
    for variant in ("advbench", "harmbench", "jailbreakbench", "jbb"):
        probes = _static_probes(variant, ["jailbreak"], 0)
        for p in probes:
            assert p.source == f"dataset:{variant}"


def test_static_probes_strategy_is_jailbreak_for_all_variants():
    for variant in _VARIANTS:
        probes = _static_probes(variant, ["jailbreak"], 0)
        for p in probes:
            assert p.strategy == "jailbreak"


def test_static_probes_empty_when_strategy_not_matching():
    """If requested strategies don't include the variant's default, return []."""
    probes = _static_probes("advbench", ["pii_extraction"], 0)
    assert probes == []


def test_static_probes_respect_count():
    probes = _static_probes("advbench", ["jailbreak"], 2)
    assert len(probes) <= 2


def test_static_probes_count_zero_returns_all():
    probes = _static_probes("advbench", ["jailbreak"], 0)
    assert len(probes) >= 1


def test_static_probes_non_empty_text():
    for variant in _VARIANTS:
        probes = _static_probes(variant, ["jailbreak"], 0)
        for p in probes:
            assert isinstance(p.prompt, str) and p.prompt.strip()


def test_static_probes_technique_set():
    for variant in _VARIANTS:
        probes = _static_probes(variant, ["jailbreak"], 0)
        for p in probes:
            assert p.technique is not None
            assert p.technique.endswith(":behavior")


def test_static_probes_no_real_harmful_content():
    """Smoke-check that placeholder probes carry the [*-style behavior placeholder] label."""
    probes = _static_probes("advbench", ["jailbreak"], 0)
    for p in probes:
        assert "placeholder" in p.prompt.lower(), (
            f"Placeholder marker missing from static probe: {p.prompt!r}"
        )


# ---------------------------------------------------------------------------
# generate() — mock path
# ---------------------------------------------------------------------------


async def test_generate_mock_returns_probes():
    source = make_dataset_source(variant="advbench")
    probes = await source.generate(
        target_desc=None,
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    assert len(probes) >= 1
    assert len(probes) <= 3


async def test_generate_mock_source_starts_with_dataset():
    source = make_dataset_source(variant="advbench")
    probes = await source.generate(
        target_desc=None,
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    for p in probes:
        assert p.source.startswith("dataset:")


async def test_generate_mock_strategy_is_jailbreak():
    source = make_dataset_source(variant="advbench")
    probes = await source.generate(
        target_desc=None,
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    for p in probes:
        assert p.strategy == "jailbreak"


async def test_generate_mock_probes_non_empty():
    source = make_dataset_source(variant="advbench")
    probes = await source.generate(
        target_desc=None,
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    assert len(probes) > 0
    for p in probes:
        assert isinstance(p.prompt, str) and p.prompt.strip()


async def test_generate_mock_returns_generated_probe_instances():
    source = make_dataset_source(variant="harmbench")
    probes = await source.generate(
        target_desc=None,
        count=4,
        strategies=["jailbreak"],
        mock=True,
    )
    for p in probes:
        assert isinstance(p, GeneratedProbe)


async def test_generate_mock_harmbench():
    source = make_dataset_source(variant="harmbench")
    probes = await source.generate(
        target_desc="a generic test chatbot",
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    assert len(probes) >= 1
    for p in probes:
        assert p.source == "dataset:harmbench"


async def test_generate_mock_jailbreakbench():
    source = make_dataset_source(variant="jailbreakbench")
    probes = await source.generate(
        target_desc=None,
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    assert len(probes) >= 1
    for p in probes:
        assert p.source == "dataset:jailbreakbench"


async def test_generate_mock_count_zero_returns_all():
    """count=0 → no cap; returns all available static probes."""
    source = make_dataset_source(variant="advbench")
    probes = await source.generate(
        target_desc=None,
        count=0,
        strategies=["jailbreak"],
        mock=True,
    )
    assert len(probes) >= 1


async def test_generate_mock_unmatched_strategy_returns_empty():
    """If strategies don't include 'jailbreak', dataset source returns []."""
    source = make_dataset_source(variant="advbench")
    probes = await source.generate(
        target_desc=None,
        count=5,
        strategies=["pii_extraction"],
        mock=True,
    )
    assert probes == []


async def test_generate_mock_target_desc_ignored():
    """target_desc is accepted but has no effect on the mock path."""
    source = make_dataset_source(variant="advbench")
    probes_with = await source.generate(
        target_desc="some target description",
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    probes_without = await source.generate(
        target_desc=None,
        count=3,
        strategies=["jailbreak"],
        mock=True,
    )
    assert len(probes_with) == len(probes_without)


# ---------------------------------------------------------------------------
# available() when datasets is absent
# ---------------------------------------------------------------------------


def test_available_returns_false_when_datasets_missing(monkeypatch):
    """When the datasets library is not installed, available() returns False."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "datasets" or name.startswith("datasets."):
            raise ImportError("datasets not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    source = DatasetSource(variant="advbench")
    assert source.available() is False


async def test_generate_falls_back_to_static_when_datasets_missing(monkeypatch):
    """When datasets cannot be imported, generate() returns static probes."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "datasets" or name.startswith("datasets."):
            raise ImportError("datasets not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    source = DatasetSource(variant="advbench")
    probes = await source.generate(
        target_desc=None,
        count=5,
        strategies=["jailbreak"],
        mock=False,  # not mock, but library unavailable
    )
    assert len(probes) > 0
    for p in probes:
        assert p.source == "dataset:advbench"
        assert p.strategy == "jailbreak"


# ---------------------------------------------------------------------------
# _VARIANTS completeness
# ---------------------------------------------------------------------------


def test_variants_map_has_required_keys():
    required = {"advbench", "harmbench", "jailbreakbench", "jbb"}
    assert required.issubset(set(_VARIANTS))


def test_variants_all_default_strategy_is_jailbreak():
    for name, (hf_id, cols, default_strategy) in _VARIANTS.items():
        assert default_strategy == "jailbreak", (
            f"Variant {name!r} has unexpected default strategy {default_strategy!r}"
        )


def test_variants_all_have_non_empty_hf_id():
    for name, (hf_id, cols, _) in _VARIANTS.items():
        assert isinstance(hf_id, str) and hf_id.strip(), f"Variant {name!r} missing HF id"


def test_variants_all_have_candidate_columns():
    for name, (_, cols, _) in _VARIANTS.items():
        assert isinstance(cols, list) and len(cols) >= 1, (
            f"Variant {name!r} has no candidate columns"
        )
