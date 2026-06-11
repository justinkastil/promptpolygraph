"""Compare module: deterministic A/B comparison of two scored runs.

Given the same corpus graded under two different targets (or two builds of the
same target), `pairwise` decides, per case, which run produced the better
response by comparing the per-case mean of non-None dimension scores, then rolls
the win/loss/tie record up overall and per category.
"""

from __future__ import annotations

from .matrix import comparability, compare_runs
from .pairwise import pairwise
from .trend import trend

__all__ = ["pairwise", "comparability", "compare_runs", "trend"]
