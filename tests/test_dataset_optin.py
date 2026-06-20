"""Responsible-use opt-in gate for fetching harmful-content datasets."""

from __future__ import annotations

import asyncio
import warnings

import pytest

from promptpolygraph.redteam.sources import dataset_source as ds


def test_optin_env_parsing(monkeypatch):
    monkeypatch.delenv("POLYGRAPH_ACCEPT_DATASET_TERMS", raising=False)
    assert ds.dataset_optin() is False
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("POLYGRAPH_ACCEPT_DATASET_TERMS", v)
        assert ds.dataset_optin() is True
    monkeypatch.setenv("POLYGRAPH_ACCEPT_DATASET_TERMS", "0")
    assert ds.dataset_optin() is False


def test_live_fetch_gated_without_optin(monkeypatch):
    """Without opt-in, even when `datasets` is 'available' the live path is not
    taken — benign placeholders are returned and a warning is emitted."""
    src = ds.DatasetSource(variant="advbench")
    monkeypatch.setattr(src, "available", lambda: True)
    monkeypatch.delenv("POLYGRAPH_ACCEPT_DATASET_TERMS", raising=False)

    called = {"live": False}
    monkeypatch.setattr(src, "_live_generate",
                        lambda **kw: called.__setitem__("live", True) or [])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        probes = asyncio.run(src.generate(target_desc=None, count=3,
                                          strategies=["jailbreak"], mock=False))
    assert called["live"] is False                 # live fetch was NOT called
    assert probes and all("dataset:advbench" in p.source for p in probes)  # benign placeholders
    assert any("RESPONSIBLE_USE" in str(x.message) for x in w)


def test_live_fetch_runs_with_optin(monkeypatch):
    src = ds.DatasetSource(variant="advbench")
    monkeypatch.setattr(src, "available", lambda: True)
    monkeypatch.setenv("POLYGRAPH_ACCEPT_DATASET_TERMS", "1")

    sentinel = [ds.GeneratedProbe(prompt="x", strategy="jailbreak",
                                  technique="t", source="dataset:advbench")]
    monkeypatch.setattr(src, "_live_generate", lambda **kw: sentinel)
    probes = asyncio.run(src.generate(target_desc=None, count=3,
                                      strategies=["jailbreak"], mock=False))
    assert probes == sentinel  # opted in -> live path used


def test_mock_always_uses_placeholders(monkeypatch):
    """mock=True never fetches, regardless of opt-in."""
    src = ds.DatasetSource(variant="advbench")
    monkeypatch.setenv("POLYGRAPH_ACCEPT_DATASET_TERMS", "1")
    monkeypatch.setattr(src, "_live_generate", lambda **kw: pytest.fail("must not fetch in mock"))
    probes = asyncio.run(src.generate(target_desc=None, count=2,
                                      strategies=["jailbreak"], mock=True))
    assert probes  # benign placeholders
