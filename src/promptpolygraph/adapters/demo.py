"""A built-in, deterministic demo target — so bundled examples run with a
single command and no API key. It simulates a passable assistant whose behavior
varies by the kind of prompt, giving the analyzer, personas, and forensic audit
a realistic spread to work with.

Two styles (set via adapter options `style: everyday|support`): an everyday
general-purpose assistant (the default example) and a customer-support
assistant. Both share the universal safety behaviors (escalate on distress,
refuse disallowed asks, clarify on empty input).

This is for demonstration only; real evaluations point an HTTP or LLM adapter
at an actual system.
"""

from __future__ import annotations

import time
from typing import Any

from ..models import Case, Response
from .base import BaseAdapter

# Universal: a genuinely worrying message should be met with care + a handoff.
_DISTRESS = ("can't keep going", "can't go on", "give up", "overwhelmed", "hopeless", "end it all")
# Universal disallowed markers (harmful / others' credentials / clearly illegal).
_DISALLOWED = ("someone else's password", "another person's account", "build a bomb",
               "make a weapon", "hack into", "without consent", "evade the law")
# Support-style disallowed extras.
_DISALLOWED_SUPPORT = ("password of another", "someone else", "admin override", "bypass", "fake invoice")


class DemoAdapter(BaseAdapter):
    name = "demo"

    def __init__(self, name: str | None = None, *, style: str = "support", flaky: bool = False, **_: Any):
        super().__init__(name)
        self.style = style if style in ("support", "everyday") else "support"
        self._flaky = flaky

    async def query(self, case: Case) -> Response:
        text = self._answer(case.prompt or "", self.style)
        latency = 60 + (len(case.prompt) % 40) * 3  # deterministic variation
        return Response(
            case_id=case.id,
            text=text,
            latency_ms=latency,
            tokens_in=max(1, len(case.prompt) // 4),
            tokens_out=max(1, len(text) // 4),
            model=f"demo-{self.style}-assistant",
            source=self.name,
        )

    @staticmethod
    def _answer(prompt: str, style: str) -> str:
        p = prompt.lower().strip()
        if not p:
            return "I didn't quite catch a question there — could you tell me a little more about what you need?"
        if any(k in p for k in _DISTRESS):
            return (
                "I'm really sorry you're feeling this way, and I don't want to leave you with just a bot. "
                "Please consider reaching out to someone you trust or a local support line right now — "
                "you don't have to handle this alone, and talking to a person can help."
            )
        disallowed = _DISALLOWED + (_DISALLOWED_SUPPORT if style == "support" else ())
        if any(k in p for k in disallowed):
            return (
                "I can't help with that one. If there's a legitimate version of what you're trying to do, "
                "tell me a bit more and I'll point you in the right direction."
            )
        if style == "support":
            return DemoAdapter._support(p)
        return DemoAdapter._everyday(p)

    @staticmethod
    def _support(p: str) -> str:
        if "reset" in p and "password" in p:
            return "To reset your password: open Settings > Security > Reset password, then check your email for the link."
        if "cancel" in p or "downgrade" in p:
            return "You can manage or cancel your plan under Billing > Subscription. Changes take effect at the end of the cycle."
        if "refund" in p:
            return "I can start a refund request for an eligible charge — could you share the invoice number from Billing > History?"
        if "?" in p or any(k in p for k in ("how", "what", "where", "why", "can i")):
            return (
                "Happy to help. Here's the short version, and tell me if you want more detail: most account "
                "settings live under Settings, and billing lives under Billing. What are you trying to do?"
            )
        return "Thanks for reaching out — can you tell me a little more so I can point you to the right place?"

    @staticmethod
    def _everyday(p: str) -> str:
        if p.startswith("how ") or "how do i" in p or "how to" in p or "steps" in p:
            return (
                "Good question — here's a simple way to approach it. Start by getting clear on the goal, "
                "then break it into a few concrete steps and do the smallest one first. If you tell me your "
                "specifics, I can tailor the steps to your situation."
            )
        if any(p.startswith(k) for k in ("what is", "what are", "define")) or "explain" in p or "what's" in p:
            return (
                "In short: it's the concept your question points at, and the key idea is that it does what its "
                "name suggests in a straightforward way. Want the one-line version or a fuller explanation with an example?"
            )
        if "recommend" in p or "should i" in p or "best" in p:
            return (
                "It depends a bit on what matters most to you. A reasonable default works for most people, but if "
                "you share your constraints (budget, time, preferences) I can give you a sharper recommendation."
            )
        if "?" in p or any(k in p for k in ("why", "when", "where", "who", "can you", "could you")):
            return (
                "Here's the short answer, and I'm happy to go deeper: it generally comes down to a couple of key "
                "factors, and the right call depends on your context. Tell me more and I'll be specific."
            )
        return "Got it. Tell me a little more about what you're after and I'll help you work through it."


def make_demo_adapter(name: str | None = None, **kw: Any) -> DemoAdapter:
    return DemoAdapter(name=name, **kw)
