"""Built-in catalog attack source — emits known, standards-mapped probe templates
with no LLM and no dependencies. This is the floor that proves the source layer
and grounds attacks even when no external tool/dataset is configured."""

from __future__ import annotations

from ..catalog import TECHNIQUES, techniques_for
from .base import GeneratedProbe


class CatalogSource:
    name = "catalog"

    def available(self) -> bool:
        return True

    async def generate(
        self,
        *,
        target_desc: str | None,
        count: int,
        strategies: list[str] | None,
        mock: bool = False,
    ) -> list[GeneratedProbe]:
        strats = strategies or sorted({t.strategy for t in TECHNIQUES})
        out: list[GeneratedProbe] = []
        for s in strats:
            for t in techniques_for(s):
                for seed in t.seeds:
                    out.append(GeneratedProbe(strategy=s, prompt=seed, source="catalog", technique=t.id))
        return out[:count] if count else out
