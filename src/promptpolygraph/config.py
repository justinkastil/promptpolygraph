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


class AnalyzeConfig(BaseModel):
    rubric: str | None = None  # path to rubric.yaml
    judges: int = 1  # ensemble size
    judge_model: str | None = None
    temperature: float = 0.0


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
    personas_path: str | None = None  # a personas.yaml for this run
    out_dir: str = "polygraph_out"
    model: str | None = None  # default model for judges/audit/generation
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
