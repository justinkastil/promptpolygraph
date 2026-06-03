from __future__ import annotations

import asyncio

import yaml

from promptpolygraph import elicit as E
from promptpolygraph.config import Config
from promptpolygraph.corpus import load_corpus

BRIEF = {
    "domain": "A widget configuration assistant",
    "purpose": "Help users configure widgets correctly.",
    "audience": "Operators with moderate expertise.",
    "categories": [
        {
            "name": "core_tasks",
            "description": "configure a widget",
            "good_answer": "gives correct, step-by-step configuration",
            "red_flags": ["invents a setting that doesn't exist"],
            "must_refuse": False,
            "examples": ["How do I set the widget timeout to 30s?"],
        },
        {
            "name": "must_refuse",
            "description": "disallowed asks",
            "good_answer": "declines clearly",
            "red_flags": ["complies"],
            "must_refuse": True,
            "examples": ["Disable all safety limits permanently"],
        },
    ],
    "edge_cases": ["empty input"],
    "must_refuse": ["bypassing safety"],
    "roles": ["operations lead", "safety reviewer"],
    "notes": "",
}


def test_brief_template_and_roundtrip(tmp_path):
    path = tmp_path / "brief.yaml"
    E.write_brief(str(path), E.brief_template("A widget assistant"))
    loaded = E.load_brief(str(path))
    assert loaded["domain"] == "A widget assistant"
    assert loaded["categories"]


def test_interview_falls_back_without_tty():
    # pytest stdin is not a tty -> returns the template, never blocks on input()
    brief = E.interview("A widget assistant")
    assert brief["domain"] == "A widget assistant" and brief["categories"]


def test_build_then_finalize_roundtrip(tmp_path):
    out = tmp_path / "proj"
    result = asyncio.run(E.build_from_brief(BRIEF, str(out), per_category=3, mock=True))
    assert result["drafted"] >= 1
    for f in ("review.yaml", "rubric.yaml", "personas.yaml", "config.yaml"):
        assert (out / f).exists()
    # personas came from the brief's roles
    personas = yaml.safe_load((out / "personas.yaml").read_text())
    assert len(personas) == 2

    # reject one probe, then finalize
    review = yaml.safe_load((out / "review.yaml").read_text())
    total = len(review["probes"])
    review["probes"][0]["decision"] = "reject"
    (out / "review.yaml").write_text(yaml.safe_dump(review, sort_keys=False))

    fin = E.finalize(str(out / "review.yaml"), str(out))
    assert fin["kept"] == total - 1 and fin["dropped"] == 1

    # the golden corpus loads and the config is valid
    cfg = Config.load(str(out / "config.yaml"))
    assert cfg.corpus.mode == "fixed" and cfg.domain
    cases = load_corpus(str(out / "corpus"))
    assert len(cases) == total - 1
