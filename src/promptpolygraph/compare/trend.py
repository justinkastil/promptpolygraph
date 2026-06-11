"""Longitudinal trend over a project's most-recent comparable runs.

`trend` selects the most recent runs that share a corpus (and, by default, the
project), orders them chronologically, and emits the same per-category trend
blocks that `compare_runs` produces — series + least-squares slope per
dimension — so a dashboard can plot a category's trajectory over a rolling
window without diffing two specific runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..models import RunMeta
from .matrix import build_category_trends, _load_summary


def _select_runs(
    runs: list[RunMeta],
    *,
    project: Optional[str],
    corpus_fingerprint: Optional[str],
    window: int,
) -> list[RunMeta]:
    """Filter + chronologically order the window of runs to trend over.

    When no `corpus_fingerprint` is given, the most recent run's corpus anchors
    the window so the series stays comparable.
    """
    pool = list(runs)
    if project is not None:
        pool = [r for r in pool if (r.project or "default") == project]

    if corpus_fingerprint is None and pool:
        # `list_runs` returns newest-first; anchor on the newest run's corpus.
        newest = max(pool, key=lambda r: r.created_at or "")
        corpus_fingerprint = newest.corpus_fingerprint

    if corpus_fingerprint is not None:
        pool = [r for r in pool if r.corpus_fingerprint == corpus_fingerprint]

    pool.sort(key=lambda r: r.created_at or "")
    if window and len(pool) > window:
        pool = pool[-window:]
    return pool


def trend(
    store,
    *,
    project: Optional[str] = None,
    corpus_fingerprint: Optional[str] = None,
    dimensions: Optional[list[str]] = None,
    out_dir: str | Path,
    window: int = 30,
) -> list[dict[str, Any]]:
    """Per-category trend blocks over the most recent comparable runs.

    Robust to <2 runs: with zero matching runs it returns []; with one run each
    dimension series has a single point and a None slope.
    """
    selected = _select_runs(
        store.list_runs(),
        project=project,
        corpus_fingerprint=corpus_fingerprint,
        window=window,
    )
    if not selected:
        return []

    summaries = [(m.run_id, _load_summary(store, m.run_id, out_dir)) for m in selected]

    if dimensions is None:
        dimensions = []
        for _, summ in summaries:
            for d in summ.get("dimensions") or []:
                if d not in dimensions:
                    dimensions.append(d)

    return build_category_trends(summaries, dimensions)
