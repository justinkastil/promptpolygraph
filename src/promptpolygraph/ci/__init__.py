"""CI integration helpers — turn a run summary + baseline diff into the feedback
a pipeline shows on a pull request (GitHub Actions annotations, a job-summary /
PR-comment markdown), independent of any single CI vendor."""

from __future__ import annotations

from .github import (
    annotations,
    emit_annotations,
    pr_comment_markdown,
    write_step_summary,
)

__all__ = ["annotations", "emit_annotations", "pr_comment_markdown", "write_step_summary"]
