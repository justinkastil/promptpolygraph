"""Corpus diversity, coverage, and redundancy measurement.

Given a set of probe cases (loaded from a corpus directory or a stored run),
report per-category counts, normalized Shannon entropy over the category
distribution, a pairwise prompt-similarity histogram, and a redundancy score
(the fraction of prompts whose nearest neighbour exceeds a similarity
threshold). Similarity uses the project's offline `MockEmbedder` by default so
results are deterministic and need no network; when no embedder is supplied the
fallback is token-overlap Jaccard.

`analyze_coverage` returns a plain dict that a report can embed verbatim.
"""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any, Sequence

from .embedders import Embedder, MockEmbedder, cosine

_TOKEN = re.compile(r"[a-z0-9]+")

# Defaults chosen to be permissive: a category is "thin" below 5 prompts, and a
# pair counts as near-duplicate above 0.9 cosine (or Jaccard) similarity.
DEFAULT_MIN_PER_CATEGORY = 5
DEFAULT_REDUNDANCY_THRESHOLD = 0.9
DEFAULT_HISTOGRAM_BINS = 10


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def jaccard(a: str, b: str) -> float:
    """Token-overlap Jaccard similarity in [0, 1]; 0 when both are empty."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def normalized_shannon_entropy(counts: Sequence[int]) -> float:
    """Shannon entropy of a category distribution, normalized to [0, 1].

    1.0 is a perfectly balanced distribution; 0.0 means all mass sits in one
    category (or there is at most one non-empty category). Normalizing by
    log(k) makes the score comparable across corpora with different category
    counts.
    """
    total = sum(c for c in counts if c > 0)
    nonzero = [c for c in counts if c > 0]
    if total <= 0 or len(nonzero) <= 1:
        return 0.0
    h = 0.0
    for c in nonzero:
        p = c / total
        h -= p * math.log(p)
    return h / math.log(len(nonzero))


def _pairwise_similarities(
    prompts: Sequence[str], vectors: Sequence[Sequence[float]] | None
) -> tuple[list[float], list[float]]:
    """All-pairs similarities plus each prompt's nearest-neighbour similarity.

    Returns `(pair_sims, nn_sims)` where `pair_sims` has one entry per unordered
    pair (i<j) and `nn_sims` has one entry per prompt (its single most-similar
    peer). Both are empty for fewer than two prompts.
    """
    n = len(prompts)
    pair_sims: list[float] = []
    nn_sims = [0.0] * n
    if n < 2:
        return pair_sims, nn_sims
    for i in range(n):
        for j in range(i + 1, n):
            if vectors is not None:
                s = cosine(list(vectors[i]), list(vectors[j]))
            else:
                s = jaccard(prompts[i], prompts[j])
            pair_sims.append(s)
            if s > nn_sims[i]:
                nn_sims[i] = s
            if s > nn_sims[j]:
                nn_sims[j] = s
    return pair_sims, nn_sims


def _histogram(values: Sequence[float], bins: int) -> list[dict[str, Any]]:
    """Fixed [0, 1] histogram so bins are comparable across corpora."""
    edges = [i / bins for i in range(bins + 1)]
    out = [
        {"lo": round(edges[i], 4), "hi": round(edges[i + 1], 4), "count": 0}
        for i in range(bins)
    ]
    for v in values:
        # Clamp into range; the top edge falls in the last bin.
        idx = min(bins - 1, max(0, int(v * bins)))
        out[idx]["count"] += 1
    return out


def _embed(prompts: Sequence[str], embedder: Embedder) -> list[list[float]]:
    return asyncio.run(embedder.embed(list(prompts)))


def analyze_coverage(
    cases: Sequence[Any],
    *,
    embedder: Embedder | None = MockEmbedder(),
    min_per_category: int = DEFAULT_MIN_PER_CATEGORY,
    redundancy_threshold: float = DEFAULT_REDUNDANCY_THRESHOLD,
    histogram_bins: int = DEFAULT_HISTOGRAM_BINS,
) -> dict[str, Any]:
    """Measure category coverage and prompt redundancy across a case set.

    `cases` is any sequence of objects exposing `.prompt` and `.category`
    (the `Case` model, or a run's stored cases). Pass `embedder=None` to force
    the token-overlap Jaccard path; the default offline `MockEmbedder` keeps the
    result deterministic. The returned dict is JSON-serializable and stable for
    a fixed input.
    """
    prompts = [getattr(c, "prompt", "") or "" for c in cases]
    categories = [getattr(c, "category", "default") or "default" for c in cases]
    n = len(prompts)

    counts: dict[str, int] = {}
    for cat in categories:
        counts[cat] = counts.get(cat, 0) + 1
    # Sort for a stable, readable order: most-populated first, then by name.
    per_category = {
        cat: counts[cat]
        for cat in sorted(counts, key=lambda k: (-counts[k], k))
    }

    entropy = normalized_shannon_entropy(list(counts.values()))

    vectors = _embed(prompts, embedder) if embedder is not None else None
    pair_sims, nn_sims = _pairwise_similarities(prompts, vectors)

    redundant = [s for s in nn_sims if s >= redundancy_threshold]
    redundancy = (len(redundant) / n) if n else 0.0
    mean_pair_sim = (sum(pair_sims) / len(pair_sims)) if pair_sims else 0.0
    max_pair_sim = max(pair_sims) if pair_sims else 0.0

    warnings: list[str] = []
    thin = {cat: c for cat, c in per_category.items() if c < min_per_category}
    for cat, c in thin.items():
        warnings.append(
            f"category '{cat}' has {c} prompt(s) (< {min_per_category})"
        )
    if redundancy > 0.5:
        warnings.append(
            f"redundancy {redundancy:.0%} of prompts exceed similarity "
            f"{redundancy_threshold:.2f} to a near neighbour"
        )

    return {
        "total_prompts": n,
        "category_count": len(per_category),
        "per_category": per_category,
        "thin_categories": thin,
        "category_entropy": round(entropy, 4),
        "similarity_metric": "cosine" if vectors is not None else "jaccard",
        "redundancy_threshold": redundancy_threshold,
        "redundancy": round(redundancy, 4),
        "redundant_prompts": len(redundant),
        "mean_pairwise_similarity": round(mean_pair_sim, 4),
        "max_pairwise_similarity": round(max_pair_sim, 4),
        "similarity_histogram": _histogram(pair_sims, histogram_bins),
        "min_per_category": min_per_category,
        "warnings": warnings,
    }
