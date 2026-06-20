"""Config/rubric JSON-schema generation + fail-fast validation."""

from __future__ import annotations

import json

from promptpolygraph import schema_gen


def test_config_and_rubric_schemas_generate():
    cs = schema_gen.config_schema()
    rs = schema_gen.rubric_schema()
    assert cs["title"] == "Config" and "properties" in cs
    assert "adapter" in cs["properties"] and "analyze" in cs["properties"]
    assert rs["title"] == "Rubric" and "dimensions" in rs["properties"]


def test_write_schemas(tmp_path):
    written = schema_gen.write_schemas(tmp_path)
    assert set(written) == {"config", "rubric"}
    doc = json.loads((tmp_path / "config.schema.json").read_text())
    assert doc["title"] == "Config"


def test_validate_good_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("name: demo\nrun:\n  concurrency: 8\nanalyze:\n  judges: 2\n")
    res = schema_gen.validate_config_file(p)
    assert res["ok"] is True and res["errors"] == []


def test_validate_bad_type_fails_with_path(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("run:\n  concurrency: not-an-int\n")
    res = schema_gen.validate_config_file(p)
    assert res["ok"] is False
    assert any("run.concurrency" in e for e in res["errors"])


def test_validate_unknown_key_warns_but_ok(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("name: demo\ntypo_field: 1\n")
    res = schema_gen.validate_config_file(p)
    assert res["ok"] is True
    assert any("typo_field" in w for w in res["warnings"])


def test_validate_missing_file():
    res = schema_gen.validate_config_file("/nonexistent/c.yaml")
    assert res["ok"] is False and "not found" in res["errors"][0]


def test_validate_rubric(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("name: r\nthreshold: 7.0\ndimensions:\n  - name: quality\n")
    assert schema_gen.validate_rubric_file(p)["ok"] is True
    bad = tmp_path / "rb.yaml"
    bad.write_text("threshold: not-a-number\n")
    assert schema_gen.validate_rubric_file(bad)["ok"] is False


def test_schema_comment():
    assert schema_gen.schema_comment("x.json") == "# yaml-language-server: $schema=x.json"


def test_cli_validate_config_exit_codes(tmp_path):
    from promptpolygraph.cli import main
    good = tmp_path / "good.yaml"
    good.write_text("name: ok\n")
    assert main(["validate-config", "--config", str(good)]) == 0
    bad = tmp_path / "bad.yaml"
    bad.write_text("analyze:\n  judges: notint\n")
    assert main(["validate-config", "--config", str(bad)]) == 1
