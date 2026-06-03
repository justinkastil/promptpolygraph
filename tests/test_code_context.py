from __future__ import annotations

from pathlib import Path

from promptpolygraph.audit.code_context import CodeIndex, build_code_context, expand_terms

SRC = str(Path(__file__).resolve().parent.parent / "src" / "promptpolygraph")


def test_expand_terms_splits_tokens():
    t = expand_terms(["edge_input", "Quality", "x"])
    assert "edge_input" in t and "edge" in t and "input" in t and "quality" in t
    assert "x" not in t  # too short


def test_index_walks_tree_and_skips_noise():
    idx = CodeIndex(SRC)
    assert idx.ok and len(idx._files) > 10
    rels = [r for r, _ in idx._files]
    assert any(r.endswith("analyzer.py") for r in rels)
    assert not any("__pycache__" in r for r in rels)


def test_context_is_relevance_ranked_and_line_numbered():
    idx = CodeIndex(SRC)
    ctx = build_code_context(SRC, ["analyzer", "assertions", "gate"], index=idx)
    assert "REPOSITORY MAP" in ctx
    assert "RELEVANT SOURCE EXCERPTS" in ctx
    assert "analyzer.py" in ctx
    # line-numbered excerpt format "   12| ..."
    assert any(seg.strip().split("|")[0].strip().isdigit() for seg in ctx.split("\n") if "|" in seg)


def test_missing_path_degrades_gracefully():
    assert build_code_context("/no/such/path/xyz", ["anything"]) == ""
    assert build_code_context(None, ["anything"]) == ""
