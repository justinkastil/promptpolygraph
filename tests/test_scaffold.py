"""CI pipeline scaffolding."""

from __future__ import annotations

import yaml

from promptpolygraph import scaffold


def test_providers_listed():
    assert set(scaffold.providers()) == {"github", "gitlab", "jenkins", "precommit"}


def test_scaffold_github_valid_yaml(tmp_path):
    res = scaffold.scaffold_ci("github", config="my.yaml", root=tmp_path)
    assert res["written"] and res["skipped"] is False
    text = (tmp_path / ".github/workflows/promptpolygraph.yml").read_text()
    doc = yaml.safe_load(text)  # must parse
    assert "jobs" in doc and "eval" in doc["jobs"] and "redteam" in doc["jobs"]
    assert "my.yaml" in text
    # GitHub Actions expression survived templating, not mangled to a single brace
    assert "${{ env.RUN }}" in text
    assert "{config}" not in text  # the placeholder was substituted


def test_scaffold_all_providers_parse(tmp_path):
    for p in ("gitlab", "precommit"):
        scaffold.scaffold_ci(p, config="c.yaml", root=tmp_path)
    yaml.safe_load((tmp_path / ".gitlab-ci.yml").read_text())
    yaml.safe_load((tmp_path / ".pre-commit-config.yaml").read_text())
    # jenkins is groovy, just assert it wrote + substituted
    scaffold.scaffold_ci("jenkins", config="c.yaml", root=tmp_path)
    jf = (tmp_path / "Jenkinsfile").read_text()
    assert "pipeline" in jf and "c.yaml" in jf and "{config}" not in jf


def test_scaffold_skips_existing_without_force(tmp_path):
    scaffold.scaffold_ci("gitlab", root=tmp_path)
    again = scaffold.scaffold_ci("gitlab", root=tmp_path)
    assert again["skipped"] is True and again["written"] is False
    forced = scaffold.scaffold_ci("gitlab", root=tmp_path, force=True)
    assert forced["written"] is True


def test_scaffold_unknown_provider(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        scaffold.scaffold_ci("travis", root=tmp_path)


def test_cli_scaffold_ci(tmp_path, monkeypatch):
    from promptpolygraph.cli import main
    monkeypatch.chdir(tmp_path)
    assert main(["scaffold-ci", "github"]) == 0
    assert (tmp_path / ".github/workflows/promptpolygraph.yml").exists()
