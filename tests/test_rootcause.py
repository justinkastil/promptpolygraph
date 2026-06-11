"""Root-cause attribution tests — the defense-pipeline ladder behind the Arena drill-down."""

from __future__ import annotations

from promptpolygraph.redteam.models import AttackAttempt, BreachVerdict
from promptpolygraph.redteam.rootcause import (
    DEFENSE_STAGES,
    STATE_BROKEN,
    STATE_HELD,
    STATE_NA,
    STATE_WEAK,
    attacker_timeline,
    attempt_root_cause,
    stage_ladder,
)


def _attempt(strategy: str, *, breached: bool, turn: int = 1, vuln_class: str | None = None) -> AttackAttempt:
    v = BreachVerdict(breached=breached, severity="high" if breached else "none",
                      vuln_class=vuln_class or (strategy if breached else "none"),
                      rationale="r", evidence="e", suggested_mitigation="fix it")
    return AttackAttempt(attacker_id="a1", strategy=strategy, turn=turn,
                         prompt="p", response="resp", verdict=v)


def test_ladder_covers_every_stage_in_order():
    ladder = stage_ladder("jailbreak", breached=True)
    assert [s["id"] for s in ladder] == [s["id"] for s in DEFENSE_STAGES]
    assert all("state" in s and "owasp" in s and "blurb" in s for s in ladder)


def test_breached_marks_one_broken_and_one_weak():
    ladder = stage_ladder("prompt_injection", breached=True)
    broken = [s for s in ladder if s["state"] == STATE_BROKEN]
    weak = [s for s in ladder if s["state"] == STATE_WEAK]
    assert [s["id"] for s in broken] == ["input_firewall"]          # primary control
    assert [s["id"] for s in weak] == ["instruction_hierarchy"]     # backstop
    # everything else is neutral
    assert {s["state"] for s in ladder if s["id"] not in ("input_firewall", "instruction_hierarchy")} == {STATE_NA}


def test_defended_marks_primary_held_no_broken():
    ladder = stage_ladder("pii_extraction", breached=False)
    assert not [s for s in ladder if s["state"] == STATE_BROKEN]
    held = [s for s in ladder if s["state"] == STATE_HELD]
    assert [s["id"] for s in held] == ["data_scope"]


def test_attempt_root_cause_fields():
    rc = attempt_root_cause(_attempt("tool_abuse", breached=True))
    assert rc["breached"] is True
    assert rc["introduced_at"] == "tool_authz"
    assert rc["introduced_stage"] == "Tool authorization"
    assert rc["backstop"] == "safety_gate"
    assert rc["mitigation"] == "fix it"
    assert rc["owasp"] and rc["atlas"]
    assert len(rc["ladder"]) == len(DEFENSE_STAGES)


def test_attempt_root_cause_defended_has_no_locus():
    rc = attempt_root_cause(_attempt("jailbreak", breached=False))
    assert rc["breached"] is False
    assert rc["introduced_at"] is None and rc["introduced_stage"] is None


def test_timeline_pinpoints_breach_turn():
    # held on turns 1-2, breaks on turn 3 (the Crescendo/PAIR escalation story)
    attempts = [
        _attempt("refusal_robustness", breached=False, turn=1),
        _attempt("refusal_robustness", breached=False, turn=2),
        _attempt("refusal_robustness", breached=True, turn=3),
    ]
    tl = attacker_timeline(attempts)
    assert [t["turn"] for t in tl["turns"]] == [1, 2, 3]
    assert tl["introduced_turn"] == 3
    assert tl["turns"][2]["root_cause"]["breached"] is True
    assert tl["turns"][0]["root_cause"]["breached"] is False
