"""Root-cause attribution for red-team findings.

The harness is black-box: it sends probes and reads responses, it does not trace
the target's internal code. So this does NOT claim to observe the target's
execution. Instead it maps each attack to the canonical **defense-in-depth**
control that should have stopped it — a six-stage guardrail pipeline aligned to
the OWASP Top-10 for LLM Apps. For a breached attempt the targeted control is
the locus where the vulnerability is introduced; its backstop is the last line
that also failed to catch it.

This is what powers the Arena's drill-down ladder: click an attacker, see the
attack progression on one side and, on the other, the defense pipeline with the
broken rung highlighted (red), its backstop (yellow), and the rest neutral — so
the root cause is clear at a glance and links straight to the mitigation.
"""

from __future__ import annotations

from typing import Any

from .catalog import standards_for

# Ordered defense-in-depth pipeline a request flows through. Each stage is a
# control an LLM application should implement; `owasp` is the Top-10 (LLM) item
# the control maps to.
DEFENSE_STAGES: tuple[dict[str, str], ...] = (
    {"id": "input_firewall", "name": "Input firewall",
     "blurb": "Treat user input as data; delimit, normalize, and screen it for injected instructions.",
     "owasp": "LLM01:Prompt Injection"},
    {"id": "instruction_hierarchy", "name": "Instruction hierarchy",
     "blurb": "Keep the system prompt and policy above anything supplied in user content.",
     "owasp": "LLM01:Prompt Injection"},
    {"id": "safety_gate", "name": "Safety policy gate",
     "blurb": "Enforce the content/safety policy on the request before answering.",
     "owasp": "LLM01:Prompt Injection"},
    {"id": "data_scope", "name": "Data access control",
     "blurb": "Scope data to the authenticated user; deny cross-user or secret access.",
     "owasp": "LLM02:Sensitive Information Disclosure"},
    {"id": "tool_authz", "name": "Tool authorization",
     "blurb": "Require authorization + confirmation for state-changing tools; least privilege.",
     "owasp": "LLM06:Excessive Agency"},
    {"id": "output_filter", "name": "Output filter",
     "blurb": "Screen the response for a leaked system prompt, PII, or disallowed content.",
     "owasp": "LLM07:System Prompt Leakage"},
)

_STAGE_BY_ID = {s["id"]: s for s in DEFENSE_STAGES}
_STAGE_ORDER = [s["id"] for s in DEFENSE_STAGES]

# strategy family -> (primary control where the class is introduced, backstop control).
_STRATEGY_STAGE: dict[str, tuple[str, str]] = {
    "jailbreak": ("safety_gate", "output_filter"),
    "prompt_injection": ("input_firewall", "instruction_hierarchy"),
    "system_prompt_leak": ("instruction_hierarchy", "output_filter"),
    "pii_extraction": ("data_scope", "output_filter"),
    "tool_abuse": ("tool_authz", "safety_gate"),
    "obfuscation": ("input_firewall", "safety_gate"),
    "refusal_robustness": ("safety_gate", "instruction_hierarchy"),
}

# Per-class default control names (also used when a guard/judge returns a hazard
# class rather than a strategy family).
_DEFAULT_STAGE = ("safety_gate", "output_filter")

# Stage states the UI colors: broken = red (vuln introduced here), weak = yellow
# (backstop that also missed), held = green (this control stopped the attack),
# na = neutral (not the relevant control for this attack class).
STATE_BROKEN = "broken"
STATE_WEAK = "weak"
STATE_HELD = "held"
STATE_NA = "na"


def _stages_for(strategy: str, vuln_class: str | None) -> tuple[str, str]:
    if strategy in _STRATEGY_STAGE:
        return _STRATEGY_STAGE[strategy]
    if vuln_class and vuln_class in _STRATEGY_STAGE:
        return _STRATEGY_STAGE[vuln_class]
    return _DEFAULT_STAGE


def stage_ladder(strategy: str, *, breached: bool, vuln_class: str | None = None) -> list[dict[str, str]]:
    """The full ordered defense pipeline with a state per stage for one attempt."""
    primary, backstop = _stages_for(strategy, vuln_class)
    ladder: list[dict[str, str]] = []
    for sid in _STAGE_ORDER:
        stage = _STAGE_BY_ID[sid]
        if breached:
            if sid == primary:
                state = STATE_BROKEN
            elif sid == backstop:
                state = STATE_WEAK
            else:
                state = STATE_NA
        else:
            state = STATE_HELD if sid == primary else STATE_NA
        ladder.append({**stage, "state": state})
    return ladder


def attempt_root_cause(attempt: Any) -> dict[str, Any]:
    """Root-cause attribution for a single attempt (one turn).

    `attempt` is an AttackAttempt (or any object with `.strategy` and a
    `.verdict` having breached/severity/vuln_class/rationale/evidence/
    suggested_mitigation). Returns a JSON-able dict the report + Arena consume.
    """
    strategy = getattr(attempt, "strategy", "") or ""
    verdict = getattr(attempt, "verdict", None)
    breached = bool(getattr(verdict, "breached", False))
    vuln_class = getattr(verdict, "vuln_class", None)
    primary, backstop = _stages_for(strategy, vuln_class)
    std = standards_for(strategy)
    return {
        "breached": breached,
        "introduced_at": primary if breached else None,
        "introduced_stage": _STAGE_BY_ID[primary]["name"] if breached else None,
        "backstop": backstop if breached else None,
        "ladder": stage_ladder(strategy, breached=breached, vuln_class=vuln_class),
        "severity": getattr(verdict, "severity", "none") if verdict else "none",
        "rationale": getattr(verdict, "rationale", "") if verdict else "",
        "evidence": getattr(verdict, "evidence", "") if verdict else "",
        "mitigation": getattr(verdict, "suggested_mitigation", "") if verdict else "",
        "owasp": std.get("owasp", ""),
        "atlas": std.get("atlas", ""),
    }


def attacker_timeline(attempts: list[Any]) -> dict[str, Any]:
    """Group + order one attacker's attempts into a turn-by-turn timeline so the
    Arena can show the attack escalation alongside the defense ladder, and pinpoint
    the turn at which a control flipped from held to broken."""
    ordered = sorted(attempts, key=lambda a: getattr(a, "turn", 0))
    turns: list[dict[str, Any]] = []
    introduced_turn: int | None = None
    for a in ordered:
        rc = attempt_root_cause(a)
        turn_no = getattr(a, "turn", 0)
        if rc["breached"] and introduced_turn is None:
            introduced_turn = turn_no
        turns.append({
            "turn": turn_no,
            "prompt": getattr(a, "prompt", ""),
            "response": getattr(a, "response", ""),
            "attempt_id": getattr(a, "id", None),
            "root_cause": rc,
        })
    return {"turns": turns, "introduced_turn": introduced_turn}
