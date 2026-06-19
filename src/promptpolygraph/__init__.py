"""PromptPolygraph — synthetic-prompt evaluation and persona-audit harness.

A local-first, cloud-agnostic harness for pushing thousands of synthetic prompts
through any web/API/LLM system, scoring the responses against a pluggable rubric
(plus deterministic assertions and an optional multi-judge ensemble), reacting to
them through a panel of personas, tracing low scores with a forensic audit, and
rendering the result as a markdown / docx / pdf / html report.
"""

from .models import (
    AssertionResult,
    AssertionSpec,
    Case,
    Dimension,
    Persona,
    Response,
    Rubric,
    RunMeta,
    Score,
    fingerprint,
)

try:  # keep in sync with the installed distribution rather than hand-editing
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("promptpolygraph")
except Exception:  # not installed (e.g. running from a source tree) — fall back
    __version__ = "0.7.0"

__all__ = [
    "AssertionResult",
    "AssertionSpec",
    "Case",
    "Dimension",
    "Persona",
    "Response",
    "Rubric",
    "RunMeta",
    "Score",
    "fingerprint",
    "__version__",
]
