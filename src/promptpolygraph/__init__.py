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

__version__ = "0.1.0"

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
