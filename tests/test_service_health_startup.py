from __future__ import annotations

from pathlib import Path

from promptpolygraph.service import readiness, startup_validate
from promptpolygraph.service.db import SqlStore
from promptpolygraph.service.settings import Settings


def _config_dir(tmp_path: Path) -> Path:
    path = tmp_path / "configs"
    path.mkdir()
    (path / "config.yaml").write_text("name: test\nmock: true\n", encoding="utf-8")
    return path


def test_startup_validation_mock_success_and_missing_live_key(tmp_path):
    settings = Settings(config_dir=str(_config_dir(tmp_path)), default_mock=True)
    ok, report = startup_validate.run(settings=settings, mock=True, environ={})
    assert ok
    assert report and {item["status"] for item in report} <= {"pass", "warn", "fail"}

    ok, report = startup_validate.run(settings=settings, mock=False, environ={})
    assert not ok
    assert next(item for item in report if item["check"] == "credentials")["status"] == "fail"


def test_startup_validation_rejects_missing_config_and_bad_schedules(tmp_path):
    missing = Settings(config_dir=str(tmp_path / "missing"), default_mock=True)
    ok, report = startup_validate.run(settings=missing, mock=True)
    assert not ok
    assert next(item for item in report if item["check"] == "configs")["status"] == "fail"

    schedules = tmp_path / "schedules.yaml"
    schedules.write_text("- name: bad\n  cron: not-a-cron\n", encoding="utf-8")
    configured = Settings(
        config_dir=str(_config_dir(tmp_path)), schedules_path=str(schedules), default_mock=True
    )
    ok, report = startup_validate.run(settings=configured, mock=True)
    assert not ok
    assert next(item for item in report if item["check"] == "schedules")["status"] == "fail"


def test_startup_validation_rejects_malformed_config(tmp_path):
    config_dir = tmp_path / "bad-configs"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("adapter: [unterminated\n", encoding="utf-8")
    settings = Settings(config_dir=str(config_dir), default_mock=True)
    ok, report = startup_validate.run(settings=settings, mock=True)
    assert not ok
    assert next(item for item in report if item["check"] == "configs")["status"] == "fail"


def test_startup_optional_llm_probe_is_offline_and_noncritical(tmp_path):
    settings = Settings(
        config_dir=str(_config_dir(tmp_path)), default_mock=True, startup_llm_check=True
    )
    ok, report = startup_validate.run(
        settings=settings, mock=True, llm_probe=lambda: (_ for _ in ()).throw(OSError("offline"))
    )
    assert ok
    assert next(item for item in report if item["check"] == "llm")["status"] == "warn"


def test_readiness_store_queue_and_optional_llm(tmp_path):
    store = SqlStore(f"sqlite:///{tmp_path / 'store.sqlite'}")
    settings = Settings(queue_max_depth=0)
    ok, checks = readiness.check(store, settings)
    assert ok
    assert {item["check"] for item in checks} == {"store", "queue", "llm"}

    store.enqueue_job({"mock": True})
    ok, checks = readiness.check(store, settings)
    assert not ok
    assert next(item for item in checks if item["check"] == "queue")["status"] == "fail"

    llm_settings = Settings(queue_max_depth=1, readiness_llm_check=True)
    assert readiness.check(store, llm_settings, llm_probe=lambda: True)[0]
    assert not readiness.check(store, llm_settings, llm_probe=lambda: False)[0]


def test_readiness_store_failure_does_not_change_liveness(monkeypatch, tmp_path):
    from promptpolygraph.service import app as service_app

    store = SqlStore(f"sqlite:///{tmp_path / 'closed.sqlite'}")
    store.engine.dispose()
    monkeypatch.setattr(service_app, "store", store)
    monkeypatch.setattr(service_app, "settings", Settings(queue_max_depth=10))
    monkeypatch.setattr(readiness, "check", lambda *_args, **_kwargs: (
        False, [{"check": "store", "status": "fail"}]
    ))
    assert service_app.healthz()["status"] == "ok"
    response = service_app.healthz_ready()
    assert response.status_code == 503


def test_readiness_reports_store_connect_failure(monkeypatch, tmp_path):
    store = SqlStore(f"sqlite:///{tmp_path / 'broken.sqlite'}")

    def fail_connect():
        raise OSError("store unavailable")

    monkeypatch.setattr(store.engine, "connect", fail_connect)
    ok, checks = readiness.check(store, Settings())
    assert not ok
    assert next(item for item in checks if item["check"] == "store")["status"] == "fail"
