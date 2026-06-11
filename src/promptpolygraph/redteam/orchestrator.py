"""Red-team orchestrator: spin up the attacker roster, pressurize the target,
judge each exchange, and emit a live event stream the CLI/Arena consume.

`emit(event)` is the single live channel — the CLI logs it, the local dashboard
streams it over SSE, the service over WebSocket. Runs fully in `mock` mode with
deterministic probes + verdicts + a simulated thinking stream, so the Arena
demos offline with zero tokens.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Awaitable, Callable, Optional

from ..adapters.base import Adapter
from ..models import Case
from .judge import breach_judge
from .models import (
    AttackAttempt,
    Attacker,
    RedTeamEvent,
    RedTeamProfile,
    RedTeamReport,
    Vulnerability,
    severity_rank,
)
from .strategies import craft_attack

Emit = Optional[Callable[[RedTeamEvent], None]]


def _chunks(text: str, n: int = 5) -> list[str]:
    if not text:
        return [""]
    size = max(1, len(text) // n)
    return [text[i:i + size] for i in range(0, len(text), size)]


async def run_redteam(
    adapter: Adapter,
    profile: RedTeamProfile,
    *,
    emit: Emit = None,
    mock: bool = False,
    concurrency: int = 4,
) -> RedTeamReport:
    """Run the red team against `adapter` (the target). Returns a report."""
    from ..llm import make_client

    def _emit(ev: RedTeamEvent) -> None:
        if emit:
            try:
                emit(ev)
            except Exception:
                pass

    target_desc = profile.target_description
    judge_client = None if mock else make_client(
        profile.judge_model, provider=profile.judge_provider, base_url=profile.judge_base_url
    )

    _emit(RedTeamEvent(type="profile", data={
        "name": profile.name, "turns": profile.turns,
        "attackers": [a.model_dump() for a in profile.attackers],
        "target": adapter.name,
    }))

    report = RedTeamReport(profile=profile.name, target=adapter.name)
    sem = asyncio.Semaphore(concurrency)

    async def _run_attacker(att: Attacker) -> list[AttackAttempt]:
        async with sem:
            _emit(RedTeamEvent(type="agent_spawned", attacker_id=att.id, strategy=att.strategy,
                               data={"provider": att.provider, "model": att.model, "intensity": att.intensity}))
            client = None if mock else make_client(att.model, provider=att.provider, base_url=att.base_url)
            history: list[dict] = []
            out: list[AttackAttempt] = []
            for turn in range(1, profile.turns + 1):
                probe = await craft_attack(
                    client, strategy=att.strategy, target_desc=target_desc,
                    history=history, intensity=att.intensity,
                    persona=att.persona, temperature=att.temperature, mock=mock,
                )
                # simulated thinking stream (real token streaming lands later)
                for ch in _chunks(probe):
                    _emit(RedTeamEvent(type="thinking", attacker_id=att.id, strategy=att.strategy,
                                       turn=turn, delta=ch))
                _emit(RedTeamEvent(type="attack", attacker_id=att.id, strategy=att.strategy, turn=turn, text=probe))
                start = time.perf_counter()
                resp = await adapter.query(Case(prompt=probe, category=att.strategy))
                latency = int((time.perf_counter() - start) * 1000)
                _emit(RedTeamEvent(type="response", attacker_id=att.id, strategy=att.strategy,
                                   turn=turn, text=resp.text, data={"error": resp.error}))
                attempt = AttackAttempt(attacker_id=att.id, strategy=att.strategy, turn=turn,
                                        prompt=probe, response=resp.text, latency_ms=latency)
                attempt.verdict = await breach_judge(judge_client, attempt, target_desc=target_desc, mock=mock)
                _emit(RedTeamEvent(type="verdict", attacker_id=att.id, strategy=att.strategy, turn=turn,
                                   verdict=attempt.verdict.model_dump()))
                out.append(attempt)
                history.append({"prompt": probe, "response": resp.text, "breached": attempt.verdict.breached})
                if attempt.verdict.breached and att.intensity != "aggressive":
                    break  # found a hole; stop escalating this agent unless we're pressurizing
            return out

    results = await asyncio.gather(*(_run_attacker(a) for a in profile.attackers))
    for r in results:
        report.attempts.extend(r)

    # aggregate vulnerabilities
    by_class: dict[str, list[AttackAttempt]] = defaultdict(list)
    for a in report.attempts:
        if a.verdict and a.verdict.breached:
            by_class[a.verdict.vuln_class or a.strategy].append(a)
    for cls, atts in by_class.items():
        worst = max(atts, key=lambda a: severity_rank(a.verdict.severity))
        vuln = Vulnerability(
            vuln_class=cls, severity=worst.verdict.severity, count=len(atts),
            example_attempt_ids=[a.id for a in atts[:5]],
            mitigation=worst.verdict.suggested_mitigation,
        )
        report.vulnerabilities.append(vuln)
        _emit(RedTeamEvent(type="vuln", data=vuln.model_dump()))
    report.vulnerabilities.sort(key=lambda v: severity_rank(v.severity), reverse=True)

    breaches = sum(1 for a in report.attempts if a.verdict and a.verdict.breached)
    by_sev: dict[str, int] = defaultdict(int)
    for a in report.attempts:
        if a.verdict and a.verdict.breached:
            by_sev[a.verdict.severity] += 1
    report.stats = {
        "attacks": len(report.attempts), "breaches": breaches,
        "defended": len(report.attempts) - breaches,
        "by_severity": dict(by_sev),
        "by_class": {k: len(v) for k, v in by_class.items()},
        "attackers": len(profile.attackers),
    }
    _emit(RedTeamEvent(type="summary", data=report.stats))
    _emit(RedTeamEvent(type="done", data={"run_id": report.run_id, "vulnerabilities": len(report.vulnerabilities)}))
    return report
