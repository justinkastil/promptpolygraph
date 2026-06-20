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


def _register_plugin_sources() -> None:
    """Register attack sources contributed by installed third-party plugins.

    Runs after built-ins so a plugin name does not silently shadow one of them
    unless it is registered last; built-in names above are stable. Failure to
    discover (no metadata, broken plugin) is a no-op.
    """
    try:
        from ...plugins import GROUP_SOURCES, load_plugins

        discovered = load_plugins(GROUP_SOURCES)
    except Exception:
        return
    for name, factory in discovered.items():
        if name in _SOURCES:
            continue  # built-ins win
        register_source(name, factory)


from .base import _SOURCES  # noqa: E402  registry dict, for the shadow check above

_register_plugin_sources()

__all__ = [
    "AttackSource",
    "GeneratedProbe",
    "register_source",
    "list_sources",
    "get_source",
]
