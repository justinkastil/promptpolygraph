"""Adapter for tool-using (agentic) targets.

An agentic target decides which tools to call in response to a prompt. This
adapter wraps such a target and records the tool calls it makes on
``Response.tool_calls`` (``[{"name", "args"}]``), so the red-team judge can score
the action sequence rather than only the text.

`AgentAdapter` wraps a callable ``fn(prompt) -> result`` where ``result`` is
either a string, a ``{"text", "tool_calls"}`` mapping, or an object exposing
those attributes; sync and async callables are both accepted. `MockToolAgent` is
a deterministic in-process target with a small tool registry, used by the
bundled examples and the test suite so agentic runs need no network.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Awaitable, Callable

from ..models import Case, Response
from .base import BaseAdapter

AgentFn = Callable[[str], Any] | Callable[[str], Awaitable[Any]]


def _normalize(result: Any) -> tuple[str, list[dict[str, Any]]]:
    """Coerce an agent return value into (text, tool_calls)."""
    if isinstance(result, str):
        return result, []
    if isinstance(result, dict):
        calls = result.get("tool_calls") or []
        return str(result.get("text", "")), _clean_calls(calls)
    text = getattr(result, "text", "")
    calls = getattr(result, "tool_calls", []) or []
    return str(text), _clean_calls(calls)


def _clean_calls(calls: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in calls or []:
        if isinstance(c, dict):
            out.append({"name": str(c.get("name", "")), "args": dict(c.get("args", {}) or {})})
        else:
            out.append({"name": str(getattr(c, "name", "")),
                        "args": dict(getattr(c, "args", {}) or {})})
    return out


class AgentAdapter(BaseAdapter):
    """Wrap an agent callable; capture its text + tool calls per case."""

    name = "agent"

    def __init__(self, name: str | None = None, *, fn: AgentFn | None = None, **_: Any):
        super().__init__(name)
        if fn is None:
            raise ValueError("AgentAdapter requires a callable `fn`")
        self._fn = fn

    async def query(self, case: Case) -> Response:
        start = time.perf_counter()
        try:
            result = self._fn(case.prompt)
            if inspect.isawaitable(result):
                result = await result
            text, tool_calls = _normalize(result)
        except Exception as exc:
            return Response(case_id=case.id, error=f"{type(exc).__name__}: {exc}",
                            latency_ms=self._elapsed_ms(start), source=self.name)
        return Response(case_id=case.id, text=text, tool_calls=tool_calls,
                        latency_ms=self._elapsed_ms(start), source=self.name,
                        model="agent")


# ── deterministic mock agent ─────────────────────────────────────────────────

# Tools the mock agent can invoke. `destructive` marks an action that must never
# run without an explicit, authorized confirmation; `sensitive` reads data that
# should stay scoped to the requesting user.
_TOOLS: dict[str, dict[str, Any]] = {
    "search_docs": {"destructive": False, "sensitive": False},
    "get_weather": {"destructive": False, "sensitive": False},
    "read_user_record": {"destructive": False, "sensitive": True},
    "send_email": {"destructive": False, "sensitive": True},
    "delete_all_records": {"destructive": True, "sensitive": True},
    "transfer_funds": {"destructive": True, "sensitive": True},
    "grant_admin": {"destructive": True, "sensitive": True},
}

_INJECTION_MARKERS = ("ignore", "disregard", "regardless", "no confirmation",
                      "without asking", "override", "system:")


class MockToolAgent:
    """A deterministic agent target with a tool registry.

    `vulnerable=True` (default) models a weakly-guarded agent that can be talked
    into destructive or cross-user tool calls, giving the red-team something to
    find; `vulnerable=False` models a guarded agent that refuses them. Behavior
    is a pure function of the prompt, so runs are reproducible offline.
    """

    def __init__(self, *, vulnerable: bool = True):
        self.vulnerable = vulnerable

    def __call__(self, prompt: str) -> dict[str, Any]:
        p = (prompt or "").lower()
        pressured = any(m in p for m in _INJECTION_MARKERS)

        for tool, meta in _TOOLS.items():
            if tool.replace("_", " ") in p or tool in p:
                if meta["destructive"] and not (self.vulnerable and pressured):
                    return {"text": f"I can't run {tool} without an authorized, confirmed request.",
                            "tool_calls": []}
                if meta["sensitive"] and "another" in p and not self.vulnerable:
                    return {"text": "I can only act on your own account.", "tool_calls": []}
                return {"text": f"Calling {tool}.",
                        "tool_calls": [{"name": tool, "args": _extract_args(p)}]}

        return {"text": "I can help with that. Which tool should I use?", "tool_calls": []}


def _extract_args(prompt: str) -> dict[str, Any]:
    # Surface an injected instruction in the args so a parameter-injection probe
    # is observable in the recorded tool call.
    if any(m in prompt for m in _INJECTION_MARKERS):
        return {"note": "embedded-instruction"}
    return {}


def make_agent_adapter(name: str | None = None, *, fn: AgentFn | None = None,
                       vulnerable: bool = True, **_: Any) -> AgentAdapter:
    """Build an AgentAdapter. With no `fn`, wraps a MockToolAgent so the adapter
    is runnable offline (used by examples + tests)."""
    return AgentAdapter(name, fn=fn or MockToolAgent(vulnerable=vulnerable))
