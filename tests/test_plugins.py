from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest

from promptpolygraph import plugins as PL
from promptpolygraph.adapters import build_adapter
from promptpolygraph.adapters.base import BaseAdapter
from promptpolygraph.config import AdapterConfig
from promptpolygraph.models import Case, Response


class _FakeAdapter(BaseAdapter):
    """Minimal adapter a fake plugin entry point resolves to."""

    def __init__(self, *, name: str = "fake", reply: str = "fake-reply", **_: object) -> None:
        super().__init__(name=name)
        self.reply = reply

    async def query(self, case: Case) -> Response:  # type: ignore[override]
        return Response(text=f"{self.reply}:{case.prompt}")


def _make_fake_entry_points(monkeypatch, mapping: dict[str, list[EntryPoint]]) -> None:
    """Patch importlib.metadata.entry_points to serve only `mapping`.

    Mirrors the 3.12 .select(group=...) surface the plugin loader feature-tests
    for, so the test exercises the same code path on any supported Python.
    """

    class _EPs:
        def select(self, *, group: str) -> list[EntryPoint]:
            return mapping.get(group, [])

    monkeypatch.setattr(PL, "entry_points", lambda: _EPs())
    PL.discovered_names.cache_clear()


def test_plugin_adapter_resolved_by_build_adapter(monkeypatch):
    ep = EntryPoint(
        name="fake",
        value="tests.test_plugins:_FakeAdapter",
        group=PL.GROUP_ADAPTERS,
    )
    _make_fake_entry_points(monkeypatch, {PL.GROUP_ADAPTERS: [ep]})

    adapter = build_adapter(AdapterConfig(type="fake", options={"reply": "hi"}))
    # The entry point loads the module fresh, so identity comparison against the
    # in-test class is unreliable; assert on the resolved type's name + behavior.
    assert type(adapter).__name__ == "_FakeAdapter"
    assert adapter.reply == "hi"


def test_builtin_adapters_still_resolve(monkeypatch):
    # Even with a registered plugin present, built-in types win and never touch
    # the plugin registry.
    ep = EntryPoint(name="fake", value="tests.test_plugins:_FakeAdapter", group=PL.GROUP_ADAPTERS)
    _make_fake_entry_points(monkeypatch, {PL.GROUP_ADAPTERS: [ep]})

    for kind in ("http", "llm", "demo", "callable"):
        opts = {"fn": (lambda p: p)} if kind == "callable" else {}
        if kind == "http":
            opts = {"url": "https://x.test"}
        adapter = build_adapter(AdapterConfig(type=kind, options=opts))
        assert adapter.name == kind


def test_unknown_type_still_raises(monkeypatch):
    _make_fake_entry_points(monkeypatch, {})
    with pytest.raises(ValueError, match="unknown adapter type"):
        build_adapter(AdapterConfig(type="nope"))


def test_load_plugins_skips_broken_entry_point(monkeypatch):
    good = EntryPoint(name="ok", value="tests.test_plugins:_FakeAdapter", group=PL.GROUP_ADAPTERS)
    broken = EntryPoint(name="bad", value="tests.test_plugins:does_not_exist", group=PL.GROUP_ADAPTERS)
    _make_fake_entry_points(monkeypatch, {PL.GROUP_ADAPTERS: [good, broken]})

    loaded = PL.load_plugins(PL.GROUP_ADAPTERS)
    assert "ok" in loaded
    assert "bad" not in loaded


def test_plugins_list_cli(monkeypatch, capsys):
    from promptpolygraph.cli import main

    ep = EntryPoint(name="fake", value="tests.test_plugins:_FakeAdapter", group=PL.GROUP_ADAPTERS)
    _make_fake_entry_points(monkeypatch, {PL.GROUP_ADAPTERS: [ep]})

    rc = main(["plugins", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    # Headings for every declared group.
    for heading in ("adapters", "sources", "judges", "reporters"):
        assert heading in out
    # Built-in adapters and the third-party one both appear.
    assert "http" in out and "callable" in out
    assert "fake" in out and "tests.test_plugins:_FakeAdapter" in out


def test_discovered_entry_points_sorted(monkeypatch):
    eps = [
        EntryPoint(name="zeta", value="m:z", group=PL.GROUP_SOURCES),
        EntryPoint(name="alpha", value="m:a", group=PL.GROUP_SOURCES),
    ]
    _make_fake_entry_points(monkeypatch, {PL.GROUP_SOURCES: eps})
    rows = PL.discovered_entry_points(PL.GROUP_SOURCES)
    assert [r[0] for r in rows] == ["alpha", "zeta"]
