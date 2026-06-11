"""Data model for the red-team engine.

This is for **authorized red-teaming of a system you own** — the goal is to
surface vulnerabilities and the guardrails that fix them, not to attack third
parties. The output is a severity-ranked vulnerability report + mitigations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..models import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


Severity = Literal["none", "low", "medium", "high", "critical"]
_SEV_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class Attacker(BaseModel):
    """One adversarial agent: a strategy family run on a chosen LLM backend."""

    id: str = Field(default_factory=lambda: new_id()[:8])
    strategy: str                      # see strategies.STRATEGIES
    provider: str = "anthropic"        # pluggable backend (anthropic | openai | ollama | …)
    model: str | None = None
    base_url: str | None = None
    intensity: str = "standard"        # mild | standard | aggressive
    persona: str = ""                  # behavioral flavor so same-model agents attack differently
    temperature: float = 0.9           # higher = more varied probes
    mode: str = "escalate"             # escalate (default) | pair | crescendo (smart multi-turn)
    converter: str | None = None       # optional probe transform (base64, rot13, many_shot, …)


class BreachVerdict(BaseModel):
    breached: bool = False
    severity: Severity = "none"
    vuln_class: str = "none"           # e.g. prompt_injection, system_prompt_leak, …
    rationale: str = ""
    evidence: str = ""
    suggested_mitigation: str = ""


class AttackAttempt(BaseModel):
    id: str = Field(default_factory=lambda: new_id()[:10])
    attacker_id: str
    strategy: str
    turn: int = 1
    prompt: str = ""
    response: str = ""
    latency_ms: int | None = None
    verdict: Optional[BreachVerdict] = None


class Vulnerability(BaseModel):
    vuln_class: str
    severity: Severity
    count: int
    example_attempt_ids: list[str] = Field(default_factory=list)
    mitigation: str = ""
    owasp: str = ""                    # OWASP Top-10 for LLM Apps id (from the catalog)
    atlas: str = ""                    # MITRE ATLAS technique id (indicative)


class RedTeamProfile(BaseModel):
    """A preconfigured (or custom) red team."""

    name: str
    description: str = ""
    attackers: list[Attacker] = Field(default_factory=list)
    turns: int = 1                     # multi-turn escalation depth per attacker
    judge_kind: str = "model"          # model (LLM reviewer) | llama_guard (safety classifier)
    judge_provider: str = "anthropic"
    judge_model: str | None = None
    judge_base_url: str | None = None
    target_description: str | None = None  # context handed to attackers + judge


class RedTeamReport(BaseModel):
    run_id: str = Field(default_factory=new_id)
    profile: str = ""
    target: str = ""                   # adapter name / target id
    created_at: str = Field(default_factory=_now)
    attempts: list[AttackAttempt] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


# ─── live event protocol (CLI log / SSE / WebSocket all consume these) ───────

RedTeamEventType = Literal[
    "profile", "agent_spawned", "thinking", "attack", "response", "verdict",
    "vuln", "summary", "done", "error",
]


class RedTeamEvent(BaseModel):
    type: RedTeamEventType
    ts: str = Field(default_factory=_now)
    attacker_id: str | None = None
    strategy: str | None = None
    turn: int | None = None
    text: str | None = None            # full text (attack/response)
    delta: str | None = None           # streamed token/chunk for "thinking"
    verdict: dict[str, Any] | None = None
    data: dict[str, Any] | None = None  # profile/summary payloads

    def to_sse(self) -> str:
        """Serialize as a Server-Sent Event frame."""
        return f"event: {self.type}\ndata: {self.model_dump_json()}\n\n"


def severity_rank(s: str) -> int:
    return _SEV_ORDER.get(s, 0)
