"""Analyze module: rubric loading, assertions, judging, gating, and diffing.

This is the grading half of PromptPolygraph. Given a corpus of Cases and the
target's Responses, it produces graded Scores (deterministic assertions plus an
LLM-or-heuristic rubric judge), rolls them up into a run summary, decides
pass/fail, and diffs against a stored baseline.
"""

from __future__ import annotations

from .analyzer import analyze_run
from .assertions import evaluate_assertions, score_assertions
from .baseline import diff_baseline, rolling_baseline_summary
from .embedders import MockEmbedder, OpenAIEmbedder, make_embedder
from .gate import case_pass, ci_exit_code, summarize
from .rubric import default_rubric, generate_rubric, load_rubric

__all__ = [
    "load_rubric",
    "default_rubric",
    "generate_rubric",
    "evaluate_assertions",
    "score_assertions",
    "analyze_run",
    "summarize",
    "case_pass",
    "ci_exit_code",
    "diff_baseline",
    "rolling_baseline_summary",
    "make_embedder",
    "MockEmbedder",
    "OpenAIEmbedder",
]
