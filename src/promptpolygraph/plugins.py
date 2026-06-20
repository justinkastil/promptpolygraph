"""Third-party plugin discovery via importlib.metadata entry points.

A plugin is any pip-installed package that declares an entry point under one of
the groups below. Each entry point's value is an import target that the relevant
subsystem resolves on demand (a factory for sources, an adapter class/builder
for adapters). Discovery is lazy and failure-tolerant: a broken or
import-erroring entry point is skipped, never fatal, so one bad plugin cannot
take down the harness.

Groups:
  promptpolygraph.adapters   adapter "type" -> adapter factory/class
  promptpolygraph.sources    red-team attack source name -> source factory
  promptpolygraph.judges     judge name -> judge factory (discovery only today)
  promptpolygraph.reporters  report format -> renderer (discovery only today)

The project dogfoods this: its own built-in adapters and sources are declared as
entry points in pyproject.toml, so the discovery path is exercised by the
package itself, not only by third parties.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import EntryPoint, entry_points
from typing import Any

# Canonical group names. Kept as module constants so callers and tests reference
# one source of truth rather than string literals.
GROUP_ADAPTERS = "promptpolygraph.adapters"
GROUP_SOURCES = "promptpolygraph.sources"
GROUP_JUDGES = "promptpolygraph.judges"
GROUP_REPORTERS = "promptpolygraph.reporters"

GROUPS = (GROUP_ADAPTERS, GROUP_SOURCES, GROUP_JUDGES, GROUP_REPORTERS)


def _entry_points_for(group: str) -> list[EntryPoint]:
    """Return entry points in `group`, normalizing the 3.10 vs 3.12 API.

    Python 3.12 added EntryPoints.select(group=...); 3.10/3.11 expose a dict-like
    mapping keyed by group. Support both without a version check by feature test.
    """
    eps = entry_points()
    select = getattr(eps, "select", None)
    if callable(select):
        return list(select(group=group))
    # 3.10/3.11: mapping group -> list[EntryPoint].
    return list(eps.get(group, []))  # type: ignore[union-attr]


def load_plugins(group: str) -> dict[str, Any]:
    """Discover and load every entry point in `group`.

    Returns a mapping of entry-point name -> loaded object. Entry points that
    fail to import are skipped (the plugin author's bug must not break the host),
    and a later duplicate name overwrites an earlier one. Not cached so newly
    installed plugins are visible without a process restart; call sites that want
    caching wrap their own merge step.
    """
    loaded: dict[str, Any] = {}
    for ep in _entry_points_for(group):
        try:
            loaded[ep.name] = ep.load()
        except Exception:
            # A broken plugin is non-fatal: omit it and continue discovery.
            continue
    return loaded


@lru_cache(maxsize=None)
def discovered_names(group: str) -> tuple[str, ...]:
    """Names declared in `group`, whether or not they import cleanly.

    Used by `plugins list` to show what is *registered*, distinct from what
    loads. Cached because the installed entry-point set is fixed for a process.
    """
    return tuple(sorted(ep.name for ep in _entry_points_for(group)))


def discovered_entry_points(group: str) -> list[tuple[str, str, str]]:
    """(name, value, dist) triples for `group`, for human-facing listings.

    `dist` is the providing distribution's name when resolvable, else "" .
    Sorted by name.
    """
    rows: list[tuple[str, str, str]] = []
    for ep in _entry_points_for(group):
        dist = getattr(getattr(ep, "dist", None), "name", "") or ""
        rows.append((ep.name, ep.value, dist))
    rows.sort(key=lambda r: r[0])
    return rows
