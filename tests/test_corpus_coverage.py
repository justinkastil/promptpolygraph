from __future__ import annotations

import json

from promptpolygraph.analyze import coverage as cov
from promptpolygraph.analyze.embedders import MockEmbedder
from promptpolygraph.models import Case


def _cases(spec: dict[str, list[str]]) -> list[Case]:
    out: list[Case] = []
    for cat, prompts in spec.items():
        for p in prompts:
            out.append(Case(prompt=p, category=cat))
    return out


def test_entropy_balanced_exceeds_imbalanced():
    balanced = [10, 10, 10, 10]
    imbalanced = [37, 1, 1, 1]
    assert cov.normalized_shannon_entropy(balanced) == 1.0
    assert cov.normalized_shannon_entropy(imbalanced) < cov.normalized_shannon_entropy(balanced)


def test_entropy_single_category_is_zero():
    assert cov.normalized_shannon_entropy([12]) == 0.0
    assert cov.normalized_shannon_entropy([0, 0]) == 0.0


def test_duplicate_prompts_yield_high_redundancy():
    # Six identical prompts: every prompt's nearest neighbour is an exact copy.
    cases = _cases({"a": ["reset my password please"] * 6})
    rep = cov.analyze_coverage(cases, redundancy_threshold=0.9)
    assert rep["redundancy"] == 1.0
    assert rep["redundant_prompts"] == 6
    assert any("redundancy" in w for w in rep["warnings"])


def test_distinct_prompts_low_redundancy():
    cases = _cases({
        "a": [
            "how do I reset my password",
            "what is the capital of France",
            "summarize the quarterly revenue figures",
            "translate this sentence into German",
            "explain photosynthesis to a child",
            "recommend a good hiking trail nearby",
        ]
    })
    rep = cov.analyze_coverage(cases, redundancy_threshold=0.9)
    assert rep["redundancy"] < 0.5
    assert not any("redundancy" in w for w in rep["warnings"])


def test_small_category_warning():
    cases = _cases({
        "big": ["p%d unique words here token%d" % (i, i) for i in range(6)],
        "thin": ["only one prompt in this small category"],
    })
    rep = cov.analyze_coverage(cases, min_per_category=5)
    assert "thin" in rep["thin_categories"]
    assert rep["thin_categories"]["thin"] == 1
    assert "big" not in rep["thin_categories"]
    assert any("thin" in w for w in rep["warnings"])


def test_deterministic_with_mock_embedder():
    cases = _cases({
        "a": ["alpha beta gamma", "delta epsilon zeta"],
        "b": ["one two three", "four five six"],
    })
    r1 = cov.analyze_coverage(cases, embedder=MockEmbedder())
    r2 = cov.analyze_coverage(cases, embedder=MockEmbedder())
    assert r1 == r2
    assert r1["similarity_metric"] == "cosine"
    # Round-trips through JSON unchanged (report-embeddable contract).
    assert json.loads(json.dumps(r1)) == r1


def test_jaccard_fallback_when_no_embedder():
    cases = _cases({"a": ["shared words here", "shared words there"]})
    rep = cov.analyze_coverage(cases, embedder=None)
    assert rep["similarity_metric"] == "jaccard"
    assert cov.jaccard("a b c", "a b c") == 1.0
    assert cov.jaccard("a b", "c d") == 0.0


def test_per_category_counts_and_histogram_shape():
    cases = _cases({"a": ["x", "y"], "b": ["z", "w", "v"]})
    rep = cov.analyze_coverage(cases)
    assert rep["per_category"] == {"b": 3, "a": 2}
    assert rep["total_prompts"] == 5
    assert rep["category_count"] == 2
    assert len(rep["similarity_histogram"]) == cov.DEFAULT_HISTOGRAM_BINS
    assert sum(b["count"] for b in rep["similarity_histogram"]) == 10  # C(5,2) pairs


def test_empty_corpus_is_safe():
    rep = cov.analyze_coverage([])
    assert rep["total_prompts"] == 0
    assert rep["redundancy"] == 0.0
    assert rep["category_entropy"] == 0.0
