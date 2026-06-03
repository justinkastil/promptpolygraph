"""Audit module: forensic root-cause tracing + human persona panel.

The forensic half traces low rubric dimensions to concrete failure modes and
ranks the highest-leverage changes; the persona half reacts to a curated sample
of responses as real users would, then reconciles that human consensus against
the rubric so we don't optimize a number at the expense of real people. A tiny
generic async multi-agent engine (``run_agent`` / ``run_agents``) drives both,
with a fully deterministic offline/mock path.
"""

from __future__ import annotations

from .engine import run_agent, run_agents
from .forensic import run_forensic
from .persona import reconcile, run_audit, run_personas

__all__ = [
    "run_agent",
    "run_agents",
    "run_forensic",
    "run_personas",
    "reconcile",
    "run_audit",
]
