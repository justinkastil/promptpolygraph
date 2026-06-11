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
from . import converters as _converters
from .catalog import standards_for
from .guard import llama_guard_verdict
from .judge import breach_judge
from .multiturn import crescendo_next, pair_next
from .models import (
    AttackAttempt,
    Attacker,
    RedTeamEvent,
    RedTeamProfile,
    RedTeamReport,
    Vulnerability,
    severity_rank,
)
from .sources import get_source
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
    extra_sources: list[str] | None = None,
    source_count: int = 25,
) -> RedTeamReport:
    """Run the red team against `adapter` (the target). Returns a report.

    `extra_sources` names OSS-grounded probe sources (e.g. ``catalog``, ``garak``,
    ``pyrit``, ``dataset:advbench``) whose probes flow through the same
    target -> breach-judge loop and into the report + Arena, attributed to the
    source rather than an LLM attacker.
    """
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

    async def _judge(attempt: AttackAttempt) -> "AttackAttempt":
        """Score one attempt with the configured judge (LLM reviewer or Llama-Guard)."""
        if profile.judge_kind == "llama_guard":
            attempt.verdict = await llama_guard_verdict(judge_client, attempt, target_desc=target_desc, mock=mock)
        else:
            attempt.verdict = await breach_judge(judge_client, attempt, target_desc=target_desc, mock=mock)
        return attempt

    async def _next_probe(att: Attacker, history: list[dict], turn: int) -> str:
        """Generate the next probe for an attacker, honoring its multi-turn mode + converter."""
        if att.mode == "pair":
            probe = await pair_next(client_for(att), strategy=att.strategy, target_desc=target_desc,
                                    history=history, intensity=att.intensity, persona=att.persona,
                                    temperature=att.temperature, mock=mock)
        elif att.mode == "crescendo":
            probe = await crescendo_next(client_for(att), strategy=att.strategy, target_desc=target_desc,
                                         history=history, turns=profile.turns, intensity=att.intensity,
                                         persona=att.persona, temperature=att.temperature, mock=mock)
        else:
            probe = await craft_attack(client_for(att), strategy=att.strategy, target_desc=target_desc,
                                       history=history, intensity=att.intensity, persona=att.persona,
                                       temperature=att.temperature, mock=mock)
        if att.converter:
            try:
                probe = _converters.apply(att.converter, probe)
            except KeyError:
                pass  # unknown converter name -> leave the probe untouched
        return probe

    _clients: dict[str, object] = {}

    def client_for(att: Attacker):
        if mock:
            return None
        if att.id not in _clients:
            _clients[att.id] = make_client(att.model, provider=att.provider, base_url=att.base_url)
        return _clients[att.id]

    async def _run_attacker(att: Attacker) -> list[AttackAttempt]:
        async with sem:
            _emit(RedTeamEvent(type="agent_spawned", attacker_id=att.id, strategy=att.strategy,
                               data={"provider": att.provider, "model": att.model, "intensity": att.intensity,
                                     "mode": att.mode, "converter": att.converter}))
            history: list[dict] = []
            out: list[AttackAttempt] = []
            for turn in range(1, profile.turns + 1):
                probe = await _next_probe(att, history, turn)
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
                await _judge(attempt)
                _emit(RedTeamEvent(type="verdict", attacker_id=att.id, strategy=att.strategy, turn=turn,
                                   verdict=attempt.verdict.model_dump()))
                out.append(attempt)
                history.append({"prompt": probe, "response": resp.text, "breached": attempt.verdict.breached})
                if attempt.verdict.breached and att.intensity != "aggressive":
                    break  # found a hole; stop escalating this agent unless we're pressurizing
            return out

    async def _run_probe(source_name: str, probe) -> AttackAttempt:
        async with sem:
            sid = f"src:{source_name}"
            _emit(RedTeamEvent(type="attack", attacker_id=sid, strategy=probe.strategy, turn=1,
                               text=probe.prompt, data={"source": source_name, "technique": probe.technique}))
            start = time.perf_counter()
            resp = await adapter.query(Case(prompt=probe.prompt, category=probe.strategy))
            latency = int((time.perf_counter() - start) * 1000)
            _emit(RedTeamEvent(type="response", attacker_id=sid, strategy=probe.strategy, turn=1,
                               text=resp.text, data={"error": resp.error}))
            attempt = AttackAttempt(attacker_id=sid, strategy=probe.strategy, turn=1,
                                    prompt=probe.prompt, response=resp.text, latency_ms=latency)
            await _judge(attempt)
            _emit(RedTeamEvent(type="verdict", attacker_id=sid, strategy=probe.strategy, turn=1,
                               verdict=attempt.verdict.model_dump()))
            return attempt

    results = await asyncio.gather(*(_run_attacker(a) for a in profile.attackers))
    for r in results:
        report.attempts.extend(r)

    # External OSS-grounded sources: pull probes, run through the same loop.
    strategies = list(dict.fromkeys(a.strategy for a in profile.attackers))
    for source_name in (extra_sources or []):
        try:
            source = get_source(source_name)
        except Exception as e:
            _emit(RedTeamEvent(type="error", data={"source": source_name, "error": str(e)}))
            continue
        _emit(RedTeamEvent(type="agent_spawned", attacker_id=f"src:{source_name}", strategy="source",
                           data={"source": source_name, "kind": "oss"}))
        try:
            probes = await source.generate(target_desc=target_desc, count=source_count,
                                           strategies=strategies, mock=mock)
        except Exception as e:
            _emit(RedTeamEvent(type="error", data={"source": source_name, "error": str(e)}))
            continue
        probe_results = await asyncio.gather(*(_run_probe(source_name, p) for p in probes))
        report.attempts.extend(probe_results)

    # aggregate vulnerabilities
    by_class: dict[str, list[AttackAttempt]] = defaultdict(list)
    for a in report.attempts:
        if a.verdict and a.verdict.breached:
            by_class[a.verdict.vuln_class or a.strategy].append(a)
    for cls, atts in by_class.items():
        worst = max(atts, key=lambda a: severity_rank(a.verdict.severity))
        std = standards_for(cls)
        vuln = Vulnerability(
            vuln_class=cls, severity=worst.verdict.severity, count=len(atts),
            example_attempt_ids=[a.id for a in atts[:5]],
            mitigation=worst.verdict.suggested_mitigation,
            owasp=std["owasp"], atlas=std["atlas"],
        )
        report.vulnerabilities.append(vuln)
        _emit(RedTeamEvent(type="vuln", data=vuln.model_dump()))
    report.vulnerabilities.sort(key=lambda v: severity_rank(v.severity), reverse=True)

    breaches = sum(1 for a in report.attempts if a.verdict and a.verdict.breached)
    by_sev: dict[str, int] = defaultdict(int)
    for a in report.attempts:
        if a.verdict and a.verdict.breached:
            by_sev[a.verdict.severity] += 1
    n = len(report.attempts)
    # OWASP Top-10 (LLM) coverage: which standards categories were breached.
    owasp_breached = sorted({v.owasp for v in report.vulnerabilities if v.owasp})
    report.stats = {
        "attacks": n, "breaches": breaches,
        "defended": n - breaches,
        "asr": round(breaches / n, 4) if n else 0.0,  # attack success rate
        "by_severity": dict(by_sev),
        "by_class": {k: len(v) for k, v in by_class.items()},
        "owasp_breached": owasp_breached,
        "attackers": len(profile.attackers),
        "sources": list(extra_sources or []),
    }
    _emit(RedTeamEvent(type="summary", data=report.stats))
    _emit(RedTeamEvent(type="done", data={"run_id": report.run_id, "vulnerabilities": len(report.vulnerabilities)}))
    return report
