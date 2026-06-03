"""Translate an API run request into a stored job payload, and back into a Config.

A job stores a self-contained payload so any worker (in any container) can
reconstruct the exact run without shared filesystem state beyond what's
referenced by path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Config
from .settings import Settings


def payload_from_request(req: Any, settings: Settings) -> dict[str, Any]:
    """Build the persisted job payload from a CreateRunRequest-like object."""
    config_path = req.config_path
    if req.config_name:
        config_path = str(Path(settings.config_dir).expanduser() / f"{req.config_name}.yaml")
    return {
        "config_path": config_path,
        "config": req.config,
        "overrides": req.overrides or {},
        "mock": settings.default_mock if req.mock is None else req.mock,
        "webhook_url": req.webhook_url,
        "formats": req.formats,
        "out_dir": settings.out_dir,
    }


def config_from_payload(payload: dict[str, Any]) -> Config:
    if payload.get("config_path"):
        cfg = Config.load(payload["config_path"])
    elif payload.get("config"):
        cfg = Config(**payload["config"])
    else:
        cfg = Config()

    ov = payload.get("overrides") or {}
    if ov.get("mode"):
        cfg.corpus.mode = ov["mode"]
    if ov.get("count") is not None:
        cfg.corpus.count = ov["count"]
    if ov.get("per_category") is not None:
        cfg.corpus.per_category = ov["per_category"]
    if ov.get("categories"):
        c = ov["categories"]
        cfg.corpus.categories = c.split(",") if isinstance(c, str) else list(c)
    if ov.get("difficulty"):
        cfg.corpus.difficulty = ov["difficulty"]
    if ov.get("concurrency") is not None:
        cfg.run.concurrency = ov["concurrency"]
    if ov.get("judges") is not None:
        cfg.analyze.judges = ov["judges"]

    if payload.get("mock") is not None:
        cfg.mock = bool(payload["mock"])
    if payload.get("out_dir"):
        cfg.out_dir = payload["out_dir"]
    return cfg
