from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from promptpolygraph.adapters import DemoAdapter
from promptpolygraph.analyze import load_rubric
from promptpolygraph.config import Config
from promptpolygraph.corpus import load_corpus
from promptpolygraph.models import Case
from promptpolygraph.persona import load_personas_file

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# (pack name, min personas, min cases)
PACKS = [
    ("everyday_assistant", 6, 36),
    ("support_bot", 5, 25),
    ("clinical_trials", 8, 50),
]


@pytest.mark.parametrize("name,min_personas,min_cases", PACKS)
def test_bundled_pack_is_valid(name: str, min_personas: int, min_cases: int):
    d = EXAMPLES / name
    assert (d / "config.yaml").exists(), f"{name} missing config.yaml"
    cfg = Config.load(str(d / "config.yaml"))

    # rubric: loads, has dimensions, and applicability/blocked_shapes only
    # reference real dimension names (the most common pack-rot bug).
    rubric = load_rubric(cfg.resolve(cfg.analyze.rubric))
    dims = set(rubric.dimension_names())
    assert dims, f"{name} rubric has no dimensions"
    for cat, dl in rubric.applicability.items():
        for dim in dl:
            assert dim in dims, f"{name}: applicability[{cat}] references unknown dim {dim!r}"
    for shape, dl in rubric.blocked_shapes.items():
        for dim in dl:
            assert dim in dims, f"{name}: blocked_shapes[{shape}] references unknown dim {dim!r}"

    # personas + corpus
    personas = load_personas_file(cfg.resolve(cfg.personas_path))
    assert len(personas) >= min_personas
    assert all(p.id and p.who for p in personas)

    cases = load_corpus(cfg.resolve(cfg.corpus.path))
    assert len(cases) >= min_cases
    # An empty prompt is a legitimate edge-input probe; just require real content overall.
    assert any(c.prompt.strip() for c in cases), f"{name} has no non-empty prompts"
    assert all(isinstance(c.prompt, str) for c in cases)


def test_demo_styles_differ():
    everyday = asyncio.run(DemoAdapter(style="everyday").query(Case(prompt="How do I plan a budget?")))
    support = asyncio.run(DemoAdapter(style="support").query(Case(prompt="How do I reset my password?")))
    assert everyday.text and support.text
    assert everyday.text != support.text
    assert "support" not in everyday.model and "everyday" in everyday.model
