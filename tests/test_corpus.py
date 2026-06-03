from __future__ import annotations

import pytest

from promptpolygraph import corpus as C
from promptpolygraph.config import CorpusConfig
from promptpolygraph.models import AssertionSpec


def test_load_example_corpus(example_dir):
    cases = C.load_corpus(str(example_dir / "corpus"))
    assert len(cases) >= 25
    cats = {c.category for c in cases}
    assert {"accuracy", "tone", "refusal", "safety", "edge_input"} <= cats
    # assertions parsed into AssertionSpec
    assert any(isinstance(a, AssertionSpec) for c in cases for a in c.assertions)


def test_load_corpus_filters_and_caps(example_dir):
    cases = C.load_corpus(
        str(example_dir / "corpus"), categories=["accuracy"], per_category=2
    )
    assert len(cases) == 2
    assert all(c.category == "accuracy" for c in cases)


def test_build_corpus_fixed(example_dir):
    cfg = CorpusConfig(mode="fixed", path=str(example_dir / "corpus"))
    cases = C.build_corpus(cfg, resolve=lambda x: x, mock=True)
    assert len(cases) >= 25


def test_build_corpus_adversarial_mock_offline():
    cfg = CorpusConfig(
        mode="adversarial", count=12, categories=["accuracy", "refusal"], seed=3
    )
    cases = C.build_corpus(cfg, resolve=lambda x: x, mock=True)
    assert len(cases) == 12
    assert {c.category for c in cases} <= {"accuracy", "refusal"}
