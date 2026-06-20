"""Core data models shared across every module.

These are the single source of truth for the data contract. Everything else
(corpus, adapters, runner, analyze, audit, report) reads and writes these types.
Pydantic v2 gives validation + clean JSON (de)serialization for the SQLite store.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Corpus ───────────────────────────────────────────────────────────────


class AssertionSpec(BaseModel):
    """A deterministic, code-checkable expectation on a response.

    `kind` is one of: contains, not_contains, regex, not_regex, equals,
    json_valid, json_schema, min_length, max_length, max_latency_ms,
    no_error. `value` carries the operand (the substring, pattern, schema,
    number, etc.). Assertions are cheap and run before any LLM judge.
    """

    kind: str
    value: Any = None
    flags: str = ""  # e.g. regex flags like "i"
    description: str = ""
    # v0.3 (additive, all optional -> old specs validate unchanged):
    weight: float = 1.0              # relative weight in the case's assertion score
    threshold: float | None = None   # per-test pass threshold on a [0,1] value (None = boolean pass)
    metric: str | None = None        # named metric this assertion contributes to
    negate: bool = False             # invert pass/value (the "not-" modifier)
    options: dict[str, Any] = Field(default_factory=dict)  # scorer-specific config


class Case(BaseModel):
    """One synthetic probe sent to the system under test."""

    id: str = Field(default_factory=new_id)
    prompt: str
    category: str = "default"
    subcategory: str | None = None
    expected_behavior: str | None = None
    red_flags: list[str] = Field(default_factory=list)
    assertions: list[AssertionSpec] = Field(default_factory=list)
    expected_shape: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── Target responses ───────────────────────────────────────────────────────


class Response(BaseModel):
    """What an Adapter returned for one Case."""

    case_id: str
    text: str = ""
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    model: str | None = None
    source: str | None = None  # adapter name
    error: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


# ─── Scoring ──────────────────────────────────────────────────────────────


class AssertionResult(BaseModel):
    kind: str
    passed: bool
    description: str = ""
    detail: str = ""
    # v0.3 (additive): continuous scorers carry a [0,1] value + weight + metric tag.
    value: float | None = None
    weight: float = 1.0
    metric: str | None = None


class Score(BaseModel):
    """The graded verdict for one response.

    `dimensions` maps each rubric dimension name to an int in [0, scale_max]
    or None (dimension not applicable to this case's category/shape). `judges`
    holds the per-judge raw dimension dicts when an ensemble is used, and
    `agreement` is the [0,1] inter-judge agreement. `verdict_pass` is the
    per-case gate result.
    """

    case_id: str
    dimensions: dict[str, Optional[int]] = Field(default_factory=dict)
    assertions: list[AssertionResult] = Field(default_factory=list)
    assertions_passed: bool | None = None
    failure_reason: str | None = None
    notes: str | None = None
    judges: list[dict[str, Any]] = Field(default_factory=list)
    agreement: float | None = None
    verdict_pass: bool | None = None
    # v0.3 (additive): weighted assertion aggregate + named/derived metric values.
    assertion_score: float | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)


# ─── Rubric ───────────────────────────────────────────────────────────────


class Dimension(BaseModel):
    name: str
    description: str = ""
    anchors: dict[str, str] = Field(default_factory=dict)  # e.g. {"10": "...", "7-9": "..."}
    metric: str | None = None  # v0.3 (additive): optional named-metric tag


class Rubric(BaseModel):
    """A pluggable scoring rubric — pure data, not code.

    `applicability` maps a category to the subset of dimension names that
    apply to it; a category absent from the map means all dimensions apply.
    `blocked_shapes` maps an expected_shape to dimensions forced to None for
    any case carrying that shape (e.g. a canned refusal has nothing to grade
    on a "helpfulness"-style dimension). Dimension applicability is expressed
    as config so the same engine fits any domain's rubric.
    """

    name: str = "default"
    dimensions: list[Dimension] = Field(default_factory=list)
    applicability: dict[str, list[str]] = Field(default_factory=dict)
    blocked_shapes: dict[str, list[str]] = Field(default_factory=dict)
    threshold: float = 7.0
    scale_max: int = 10
    notes: str = ""

    def dimension_names(self) -> list[str]:
        return [d.name for d in self.dimensions]

    def applies(self, dim: str, category: str, shape: str | None) -> bool:
        """Whether `dim` is graded for a case in `category` with `shape`."""
        if shape is not None and dim in self.blocked_shapes.get(shape, []):
            return False
        allowed = self.applicability.get(category)
        if allowed is None:
            return True
        return dim in allowed


# ─── Personas ─────────────────────────────────────────────────────────────


class Persona(BaseModel):
    """A distinct individual who reacts to responses as a real user would."""

    id: str
    who: str
    focus: str = ""


# ─── Run metadata ─────────────────────────────────────────────────────────


class RunMeta(BaseModel):
    run_id: str = Field(default_factory=new_id)
    schema_version: int = 1  # record-format version; see migrations.py
    name: str = "polygraph-run"
    created_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None
    mode: str = "fixed"
    adapter: str = ""
    model: str | None = None
    total_cases: int = 0
    completed_cases: int = 0
    corpus_fingerprint: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    # v0.3 (additive) — run lineage for comparison/trend. All optional.
    project: str = "default"
    rubric_fingerprint: str | None = None
    config_fingerprint: str | None = None
    sut_git_sha: str | None = None      # git SHA of the system under test, if provided
    sut_ref: str | None = None          # branch / tag / PR ref of the SUT
    labels: dict[str, str] = Field(default_factory=dict)  # ci-run-id, actor, env, ...
    # v1.1 (additive) — identity of the judge that graded this run, so a score
    # delta between two runs can be attributed to the SUT rather than to a
    # silently swapped judge. Populated best-effort; empty/None on mock paths.
    judge_meta: dict[str, Any] = Field(default_factory=dict)


def fingerprint(cases: list[Case]) -> str:
    """Stable content hash of a corpus, for run-over-run identity.

    Only the semantic content (prompt + category + subcategory) participates,
    so re-serializing or reordering metadata does not change the fingerprint.
    """

    payload = sorted(
        (c.prompt, c.category, c.subcategory or "") for c in cases
    )
    blob = json.dumps(payload, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def rubric_fingerprint(rubric: "Rubric") -> str:
    """Stable hash of the scoring rubric (cosmetic `notes` excluded), so two
    runs are only score-comparable when they were graded the same way."""
    payload = rubric.model_dump(mode="json")
    payload.pop("notes", None)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def config_fingerprint(config: dict[str, Any]) -> str:
    """Stable hash of the run config, excluding fields that don't affect the
    system-under-test's answers (output dir, mock flag)."""
    norm = {k: v for k, v in (config or {}).items() if k not in ("out_dir", "mock")}
    blob = json.dumps(norm, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ─── Judge identity ─────────────────────────────────────────────────────────

# Fields of judge_meta that define grading identity. `mock` is excluded: the
# heuristic-vs-real distinction is handled separately and a run with no judge
# meta (older records) must not falsely compare-equal to a real-judge run only
# because both lack a mock flag.
_JUDGE_IDENTITY_KEYS = ("model", "provider", "temperature", "system_prompt_hash")


def system_prompt_hash(text: str | None) -> str | None:
    """Stable short hash of a judge's system prompt, or None for empty input."""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def judge_meta_differs(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """Whether two runs were graded by a materially different judge.

    Compares only the identity keys (model, provider, temperature,
    system_prompt_hash). Two empty/absent judge_meta dicts compare equal so
    pre-v1.1 runs do not raise a spurious drift flag against each other.
    """
    da = a or {}
    db = b or {}
    return any(da.get(k) != db.get(k) for k in _JUDGE_IDENTITY_KEYS)
