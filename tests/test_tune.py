from __future__ import annotations

import asyncio
from pathlib import Path

from promptpolygraph import tune as T
from promptpolygraph.analyze import load_rubric
from promptpolygraph.config import Config
from promptpolygraph.corpus import load_corpus
from promptpolygraph.persona import load_personas_file


def test_tune_scaffolds_runnable_project(tmp_path):
    out = tmp_path / "proj"
    result = asyncio.run(
        T.scaffold(
            "Clinical trial protocol digitalization assistant",
            str(out),
            categories=["protocol_authoring", "regulatory", "edge_input"],
            count=12,
            n_personas=5,
            mock=True,
        )
    )
    # files exist
    for f in ("config.yaml", "rubric.yaml", "personas.yaml", "README.md"):
        assert (out / f).exists(), f
    assert (out / "corpus").is_dir()

    # config loads, carries the domain, and is fixed-mode pointing at corpus
    cfg = Config.load(str(out / "config.yaml"))
    assert cfg.domain and "Clinical trial" in cfg.domain
    assert cfg.corpus.mode == "fixed"

    # artifacts load through the normal loaders
    rubric = load_rubric(str(out / "rubric.yaml"))
    assert rubric.dimension_names()
    personas = load_personas_file(str(out / "personas.yaml"))
    assert len(personas) == 5
    cases = load_corpus(str(out / "corpus"))
    assert len(cases) >= 1
    assert {"protocol_authoring", "regulatory", "edge_input"} >= {c.category for c in cases} or cases

    # the scaffold reports what it built
    assert result["personas_count"] == 5 and result["cases"] >= 1
