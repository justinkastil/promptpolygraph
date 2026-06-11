"""Pluggable attack sources — where probes come from, beyond LLM improvisation.

A source yields `GeneratedProbe`s for given strategy families; the orchestrator
runs each through the target + breach judge in the same loop (so they show up in
the report + Arena, attributed to their source). Built-in `catalog` source needs
no deps and no LLM; garak / PyRIT / dataset sources register themselves when the
optional `[redteam]` extra is installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class GeneratedProbe:
    strategy: str
    prompt: str
    source: str
    technique: str | None = None


@runtime_checkable
class AttackSource(Protocol):
    name: str

    def available(self) -> bool:
        """Whether this source's optional dependency is importable."""
        ...

    async def generate(
        self,
        *,
        target_desc: str | None,
        count: int,
        strategies: list[str],
        mock: bool = False,
    ) -> list[GeneratedProbe]:
        ...


_SOURCES: dict[str, Callable[..., AttackSource]] = {}


def register_source(name: str, factory: Callable[..., AttackSource]) -> None:
    _SOURCES[name] = factory


def list_sources() -> list[str]:
    return list(_SOURCES)


def get_source(name: str, **kwargs: Any) -> AttackSource:
    if name not in _SOURCES:
        raise KeyError(f"unknown attack source: {name!r}. Available: {', '.join(_SOURCES) or '(none)'}")
    return _SOURCES[name](**kwargs)
