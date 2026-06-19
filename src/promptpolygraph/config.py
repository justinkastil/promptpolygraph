"""Run configuration — loaded from a YAML file and/or overridden by CLI flags.

One `Config` object wires together the adapter, corpus, runner, analyzer, and
audit settings for a run. Every field has a sane default so a bare `Config()`
is runnable (against the callable adapter, in mock mode).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, PrivateAttr


class AdapterConfig(BaseModel):
    type: str = "callable"  # callable | http | llm
    name: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class CorpusConfig(BaseModel):
    mode: str = "fixed"  # fixed | varied | adversarial | hybrid
    path: str | None = None  # directory of <category>.json probe files
    count: int | None = None
    per_category: int | None = None
    categories: list[str] = Field(default_factory=list)
    difficulty: str = "standard"  # mild | standard | aggressive (adversarial)
    seed: int | None = None
    seed_bank: str | None = None  # path to seed examples for generation


class RunConfig(BaseModel):
    concurrency: int = 20
    rps: float | None = None  # requests-per-second cap (None = uncapped)
    timeout_s: float = 60.0
    retries: int = 2
    resume: bool = True


class MetricSpec(BaseModel):
    """A named/derived metric. `formula` is a safe expression over named metrics
    + dimension means (e.g. "2*precision*recall/(precision+recall+1e-9)" for F1)."""

    name: str
    formula: str | None = None  # None = a plain named metric aggregated from scorers
    aggregate: str = "mean"  # mean | min | max | p50 | p95 | rate
    threshold: float | None = None  # if set, the metric participates in the gate


# A loose mirror of models.AssertionSpec for config-declared shared assertions
# (kept here to avoid a config->models import cycle; coerced to AssertionSpec downstream).
class AssertionSpecModel(BaseModel):
    kind: str
    value: Any = None
    flags: str = ""
    description: str = ""
    weight: float = 1.0
    threshold: float | None = None
    metric: str | None = None
    negate: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class ScorersConfig(BaseModel):
    # Custom-code (python/callable) assertion sandbox: disabled (CI-safe default) |
    # expr (AST-restricted expression) | subprocess (separate process, timeout).
    sandbox: str = "disabled"
    shared: list[AssertionSpecModel] = Field(default_factory=list)  # assertions applied to every case


class EmbeddersConfig(BaseModel):
    provider: str = "mock"  # mock (deterministic offline) | openai
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class LLMBackendConfig(BaseModel):
    """Backend for the grader/judge, audit agents, and corpus generation.
    `anthropic` (default, needs ANTHROPIC_API_KEY) | `openai` | `ollama` |
    `openai-compatible` | `vllm` | `lmstudio`. Local providers (ollama, …) need
    no key, so the whole eval can run on a local model. The system *under test*
    is configured separately via `adapter:`."""

    provider: str = "anthropic"
    base_url: str | None = None  # defaults: ollama -> http://localhost:11434/v1, else OpenAI
    api_key_env: str | None = None


class AnalyzeConfig(BaseModel):
    rubric: str | None = None  # path to rubric.yaml
    judges: int = 1  # ensemble size
    judge_model: str | None = None
    temperature: float = 0.0
    dimension_weights: dict[str, float] = Field(default_factory=dict)  # weighted-gate dims
    gate_mode: str = "strict"  # strict (every applicable dim >= threshold) | weighted
    # Statistical rigor (additive; defaults preserve the strict point-estimate gate).
    confidence: float = 0.95        # confidence level for reported intervals
    respect_ci: bool = False        # when True the gate returns "inconclusive" (not fail)
                                    # if the threshold falls inside a metric's CI band
    min_sample_warn: int = 30       # warn when a category/metric is graded on fewer cases


class RedTeamConfig(BaseModel):
    profile: str = "all_frontier"   # out-of-the-box team (a built-in profile name or a custom one)
    turns: int | None = None        # override the profile's escalation depth
    concurrency: int = 4
    target_description: str | None = None  # context handed to attackers + judge
    # External probe sources run through the same target->judge loop as the LLM
    # attackers. "catalog" is always available (no deps); garak / pyrit / deepteam
    # / dataset:* register when the optional `[redteam]` extra is installed.
    sources: list[str] = Field(default_factory=list)
    source_count: int = 25          # max probes drawn from each external source
    # Local checkout of the target system, enabling the code-grounded root-cause
    # ladder (the model traces a breach to real file:line loci). None -> the
    # abstract defense-stage ladder. Reuses the audit's code-reading; no remote.
    code_path: str | None = None
    # The code-dive (reading your source) defaults to a LOCAL model so source
    # never leaves the machine. Frontier providers are allowed only with explicit
    # consent, and `air_gap` hard-refuses any non-local provider for code dives.
    code_dive_provider: str = "ollama"
    code_dive_model: str | None = None
    code_dive_base_url: str | None = None
    air_gap: bool = False


class ReportConfig(BaseModel):
    template: str = "default"  # built-in template set: default | minimal
    template_dir: str | None = None  # a custom template directory (overrides built-in)
    formats: list[str] = Field(default_factory=lambda: ["md", "html"])
    branding: dict[str, Any] = Field(default_factory=dict)  # title, accent (hex), logo


class AuditConfig(BaseModel):
    enabled: bool = True
    personas: list[str] = Field(default_factory=list)  # explicit persona ids
    persona_pool: int | None = None  # sample N from the library
    tailor_personas: bool = False  # when a domain is set, generate a domain-specific panel
    forensic: bool = True
    code_path: str | None = None  # optional source tree for root-cause tracing
    sample_per_category: int = 3  # responses surfaced to personas per category


class Config(BaseModel):
    name: str = "polygraph-run"
    adapter: AdapterConfig = Field(default_factory=AdapterConfig)
    corpus: CorpusConfig = Field(default_factory=CorpusConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    analyze: AnalyzeConfig = Field(default_factory=AnalyzeConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    redteam: RedTeamConfig = Field(default_factory=RedTeamConfig)
    scorers: ScorersConfig = Field(default_factory=ScorersConfig)
    embedders: EmbeddersConfig = Field(default_factory=EmbeddersConfig)
    metrics: list[MetricSpec] = Field(default_factory=list)  # named/derived metrics
    personas_path: str | None = None  # a personas.yaml for this run
    out_dir: str = "polygraph_out"
    model: str | None = None  # default model NAME for judges/audit/generation
    llm: LLMBackendConfig = Field(default_factory=LLMBackendConfig)  # judge/audit/gen backend
    mock: bool = False  # offline deterministic mode (no API calls)
    # One-line description of the system under test / expertise area. Tailors
    # generated prompts (and, with audit.tailor_personas, the persona panel) to
    # this domain — e.g. "Clinical trial protocol digitalization assistant".
    domain: str | None = None

    _base_dir: Path | None = PrivateAttr(default=None)

    model_config = {"extra": "ignore"}

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        if path is None:
            return cls()
        data = yaml.safe_load(Path(path).expanduser().read_text()) or {}
        cfg = cls(**data)
        cfg._base_dir = Path(path).expanduser().resolve().parent
        return cfg

    def resolve(self, rel: str | None) -> str | None:
        """Resolve a path relative to the config file's directory."""
        if rel is None:
            return None
        p = Path(rel).expanduser()
        if p.is_absolute() or self._base_dir is None:
            return str(p)
        return str((self._base_dir / p).resolve())
