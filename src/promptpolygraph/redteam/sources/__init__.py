"""Attack-source registry.

The built-in `catalog` source is always available (no deps, no LLM). Optional
OSS-grounded sources — garak, PyRIT, DeepTeam, and on-demand datasets
(AdvBench / HarmBench / JailbreakBench) — register themselves only when their
module imports cleanly, so a bare install never breaks and `[redteam]` extras
light them up. Each registration is wrapped so a missing dependency is a no-op,
not an import error.
"""

from __future__ import annotations

from .base import (
    AttackSource,
    GeneratedProbe,
    get_source,
    list_sources,
    register_source,
)
from .catalog_source import CatalogSource

register_source("catalog", lambda **kw: CatalogSource())


def _try_register(module: str, attr: str, *names: str) -> None:
    """Import an optional source module and register its factory under each name.
    Silent no-op if the module (or its optional dependency) isn't importable."""
    try:
        mod = __import__(f"{__name__}.{module}", fromlist=[attr])
        factory = getattr(mod, attr)
    except Exception:
        return
    for n in names:
        register_source(n, factory)


# Optional, OSS-grounded sources (registered iff their deps import cleanly).
_try_register("garak_source", "make_garak_source", "garak")
_try_register("pyrit_source", "make_pyrit_source", "pyrit")
_try_register("deepteam_source", "make_deepteam_source", "deepteam")
_try_register("dataset_source", "make_dataset_source", "dataset", "datasets")

__all__ = [
    "AttackSource",
    "GeneratedProbe",
    "register_source",
    "list_sources",
    "get_source",
]
