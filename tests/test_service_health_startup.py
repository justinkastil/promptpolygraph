from pathlib import Path

from promptpolygraph.service import readiness, startup_validate
from promptpolygraph.service.db import SqlStore
from promptpolygraph.service.settings import Settings


def _config_dir(tmp_path: Path) -> Path:
    path = tmp_path / "configs"
    path.mkdir()
    (path / "config.yaml").write_text("name: test\nmock: true\n", encoding="utf-8")
    return path


def test_startup_pass_fail_and_status_contract(tmp_path):
    settings = Settings(config_dir=str(_config_dir(tmp_path)), default_mock=True)
    ok, report = startup_validate.run(settings=settings, mock=True, environ={})
    assert ok
    assert report and {item["status"] for item in report} <= {"pass", "warn", "fail"}
    ok, report = startup_validate.run(settings=settings, mock=False, environ={})
    assert not ok
    assert next(x for x in report if x["check"] == "credentials")["status"] == "fail"


def test_startup_rejects_missing_malformed_inputs(tmp_path):
    ok, report = startup_validate.run(
        settings=Settings(config_dir=str(tmp_path / "missing")), mock=True
    )
    assert not ok
    assert next(x for x in report if x["check"] == "configs")["status"] == "fail"

    config_dir = tmp_path / "bad-configs"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("adapter: [unterminated\n", encoding="utf-8")
    schedule = tmp_path / "schedules.yaml"
    schedule.write_text("- cron: not-a-cron\n", encoding="utf-8")
    ok, report = startup_validate.run(
        settings=Settings(config_dir=str(config_dir), schedules_path=str(schedule)), mock=True
    )
    assert not ok
    assert {x["check"] for x in report if x["status"] == "fail"} == {"configs", "schedules"}


def test_startup_llm_failure_warns(tmp_path):
    settings = Settings(config_dir=str(_config_dir(tmp_path)), startup_llm_check=True)
    ok, report = startup_validate.run(
        settings=settings, mock=True,
        llm_probe=lambda: (_ for _ in ()).throw(OSError("offline")),
    )
    assert ok
    assert next(x for x in report if x["check"] == "llm")["status"] == "warn"


def test_readiness_queue_and_llm_thresholds(tmp_path):
    store = SqlStore(f"sqlite:///{tmp_path / 'store.sqlite'}")
    settings = Settings(queue_max_depth=0)
    assert readiness.check(store, settings)[0]
    store.enqueue_job({"mock": True})
    ok, report = readiness.check(store, settings)
    assert not ok
    assert next(x for x in report if x["check"] == "queue")["status"] == "fail"
    llm_settings = Settings(queue_max_depth=1, readiness_llm_check=True)
    assert readiness.check(store, llm_settings, lambda: True)[0]
    assert not readiness.check(store, llm_settings, lambda: False)[0]


def test_store_failure_and_liveness_separation(monkeypatch, tmp_path):
    from promptpolygraph.service import app as service_app

    store = SqlStore(f"sqlite:///{tmp_path / 'broken.sqlite'}")
    monkeypatch.setattr(store.engine, "connect", lambda: (_ for _ in ()).throw(OSError("down")))
    ok, report = readiness.check(store, Settings())
    assert not ok
    assert next(x for x in report if x["check"] == "store")["status"] == "fail"
    monkeypatch.setattr(readiness, "check", lambda *_: (False, report))
    assert service_app.healthz()["status"] == "ok"
    assert service_app.healthz_ready().status_code == 503
