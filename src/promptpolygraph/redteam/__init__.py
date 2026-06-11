"""Red-team engine — authorized adversarial testing of a system you own.

A roster of attacker agents (mixed LLM backends) pressurizes the target across
strategy families; a breach judge scores each exchange; the result is a
severity-ranked vulnerability report with mitigations. A live `RedTeamEvent`
stream drives the CLI log and the Arena UI (SSE / WebSocket). Runs offline in
mock mode.
"""

from __future__ import annotations

from .models import (
    AttackAttempt,
    Attacker,
    BreachVerdict,
    RedTeamEvent,
    RedTeamProfile,
    RedTeamReport,
    Vulnerability,
)
from .orchestrator import run_redteam
from .profiles import BUILTIN_PROFILES, get_profile, list_profiles
from .strategies import STRATEGIES

__all__ = [
    "run_redteam",
    "get_profile",
    "list_profiles",
    "BUILTIN_PROFILES",
    "STRATEGIES",
    "RedTeamProfile",
    "RedTeamReport",
    "RedTeamEvent",
    "AttackAttempt",
    "Attacker",
    "BreachVerdict",
    "Vulnerability",
]
