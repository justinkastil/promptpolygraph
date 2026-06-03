"""Cron-driven recurring runs.

A schedules YAML enqueues runs on a cron expression:

    - name: nightly-fixed
      cron: "0 2 * * *"          # standard 5-field cron (min hour dom mon dow)
      config_name: support_bot   # or config_path / inline config
      overrides: { mode: fixed }
      mock: false

The scheduler only enqueues jobs; workers execute them, so a schedule fans out
across the same worker pool as ad-hoc runs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .db import SqlStore
from .settings import Settings

log = logging.getLogger("promptpolygraph.service.scheduler")


def _enqueue(store: SqlStore, settings: Settings, spec: dict[str, Any]) -> None:
    config_path = spec.get("config_path")
    if spec.get("config_name"):
        config_path = str(Path(settings.config_dir).expanduser() / f"{spec['config_name']}.yaml")
    payload = {
        "config_path": config_path,
        "config": spec.get("config"),
        "overrides": spec.get("overrides", {}),
        "mock": spec.get("mock", settings.default_mock),
        "webhook_url": spec.get("webhook_url", settings.webhook_url),
        "formats": spec.get("formats"),
        "out_dir": settings.out_dir,
    }
    ids = store.enqueue_job(payload, priority=spec.get("priority", 0))
    log.info("scheduled '%s' enqueued run=%s", spec.get("name"), ids["run_id"])


def start_scheduler(store: SqlStore, settings: Settings) -> BackgroundScheduler | None:
    if not settings.schedules_path:
        return None
    path = Path(settings.schedules_path).expanduser()
    if not path.exists():
        log.warning("schedules file not found: %s", path)
        return None
    specs = yaml.safe_load(path.read_text()) or []
    scheduler = BackgroundScheduler()
    for spec in specs:
        cron = spec.get("cron")
        if not cron:
            continue
        scheduler.add_job(
            _enqueue, CronTrigger.from_crontab(cron),
            args=[store, settings, spec], id=spec.get("name"), replace_existing=True,
        )
        log.info("registered schedule '%s' cron='%s'", spec.get("name"), cron)
    scheduler.start()
    return scheduler
