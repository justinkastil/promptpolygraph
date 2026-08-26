"""Startup validation for service configuration dependencies."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from apscheduler.triggers.cron import CronTrigger

from ..config import Config
from .settings import Settings, get_settings

Probe = Callable[[], Any]


def _item(check: str, status: str, detail: str) -> dict[str, str]:
    return {"check": check, "status": status, "detail": detail}


def _validate_schedules(path: Path) -> int:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return 0
    if not isinstance(data, list):
        raise ValueError("schedules document must be a list")
    for index, spec in enumerate(data):
        if not isinstance(spec, dict):
            raise ValueError(f"schedule {index} must be a mapping")
        cron = spec.get("cron")
        if not isinstance(cron, str) or not cron.strip():
            raise ValueError(f"schedule {index} is missing cron")
        CronTrigger.from_crontab(cron)
    return len(data)


def run(
    *,
    settings: Settings | None = None,
    mock: bool | None = None,
    environ: Mapping[str, str] | None = None,
    llm_probe: Probe | None = None,
) -> tuple[bool, list[dict[str, str]]]:
    """Validate startup dependencies and return ``(ok, per_check_report)``.

    ``environ`` and ``llm_probe`` are injectable to keep validation fully
    offline in tests. Optional LLM failures are warnings; credentials, config,
    and configured schedules are critical.
    """
    cfg = settings or get_settings()
    env = os.environ if environ is None else environ
    mock_mode = cfg.default_mock if mock is None else mock
    report: list[dict[str, str]] = []

    if mock_mode:
        report.append(_item("credentials", "pass", "mock mode does not require a live API key"))
    elif env.get("ANTHROPIC_API_KEY", "").strip():
        report.append(_item("credentials", "pass", "ANTHROPIC_API_KEY is present"))
    else:
        report.append(_item("credentials", "fail", "ANTHROPIC_API_KEY is required in live mode"))

    config_dir = Path(cfg.config_dir).expanduser()
    try:
        if not config_dir.is_dir():
            raise FileNotFoundError(f"config directory not found: {config_dir}")
        paths = sorted(config_dir.glob("*.yaml")) + sorted(config_dir.glob("*.yml"))
        if not paths:
            raise FileNotFoundError(f"no YAML configs found in: {config_dir}")
        loaded = 0
        for path in paths:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            # CONFIG_DIR commonly also contains list-shaped personas and
            # schedules. Only mapping-shaped run configurations are Configs.
            if isinstance(document, dict):
                Config.load(path)
                loaded += 1
        if not loaded:
            raise ValueError(f"no run configurations found in: {config_dir}")
        report.append(_item("configs", "pass", f"loaded {loaded} config file(s)"))
    except Exception as exc:
        report.append(_item("configs", "fail", str(exc)))

    if not cfg.schedules_path:
        report.append(_item("schedules", "pass", "no schedules file configured"))
    else:
        path = Path(cfg.schedules_path).expanduser()
        try:
            if not path.is_file():
                raise FileNotFoundError(f"schedules file not found: {path}")
            count = _validate_schedules(path)
            report.append(_item("schedules", "pass", f"parsed {count} schedule(s)"))
        except Exception as exc:
            report.append(_item("schedules", "fail", str(exc)))

    if not cfg.startup_llm_check:
        report.append(_item("llm", "pass", "optional LLM probe disabled"))
    elif llm_probe is None:
        report.append(_item("llm", "warn", "LLM probe enabled but no probe was supplied"))
    else:
        try:
            result = llm_probe()
            if result is False:
                raise RuntimeError("probe returned false")
            report.append(_item("llm", "pass", "LLM probe succeeded"))
        except Exception as exc:
            report.append(_item("llm", "warn", f"LLM probe failed: {exc}"))

    return not any(item["status"] == "fail" for item in report), report
