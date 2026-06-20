"""Tests for the subprocess scorer trust boundary (issue #40).

The subprocess sandbox runs an unrestricted interpreter, so it must (a) refuse
to run without an explicit opt-in and (b) never expose provider/secret env vars
to the child process when it does run.
"""

from __future__ import annotations

import asyncio

import pytest

from promptpolygraph.analyze.assertions import (
    _is_secret_env,
    _minimal_subprocess_env,
    score_assertions,
)
from promptpolygraph.models import AssertionSpec, Case, Response


def _run(coro):
    return asyncio.run(coro)


def _python_case(expr: str) -> Case:
    return Case(prompt="x", assertions=[AssertionSpec(kind="python", options={"expr": expr})])


# ─── Opt-in gate ─────────────────────────────────────────────────────────────


def test_subprocess_refused_without_opt_in(monkeypatch):
    monkeypatch.delenv("POLYGRAPH_ALLOW_SUBPROCESS", raising=False)
    case = _python_case("len(output) > 0")
    resp = Response(case_id=case.id, text="anything")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is False
    assert "refused" in r[0].detail
    assert "allow_subprocess" in r[0].detail


def test_subprocess_runs_with_config_opt_in(monkeypatch):
    monkeypatch.delenv("POLYGRAPH_ALLOW_SUBPROCESS", raising=False)
    case = _python_case("len(output) == 5")
    resp = Response(case_id=case.id, text="hello")
    r, _, _ = _run(
        score_assertions(case, resp, sandbox="subprocess", allow_subprocess=True)
    )
    assert r[0].passed is True


def test_subprocess_runs_with_env_opt_in(monkeypatch):
    monkeypatch.setenv("POLYGRAPH_ALLOW_SUBPROCESS", "1")
    case = _python_case("output == 'hello'")
    resp = Response(case_id=case.id, text="hello")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is True


@pytest.mark.parametrize("val", ["0", "false", "no", "", "off"])
def test_env_opt_in_only_truthy_values(monkeypatch, val):
    monkeypatch.setenv("POLYGRAPH_ALLOW_SUBPROCESS", val)
    case = _python_case("True")
    resp = Response(case_id=case.id, text="x")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is False
    assert "refused" in r[0].detail


# ─── Secret stripping ────────────────────────────────────────────────────────


def test_subprocess_cannot_read_secret_env(monkeypatch):
    # A real-looking provider key the child must NOT be able to observe.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FAKE-do-not-leak")
    monkeypatch.setenv("POLYGRAPH_ALLOW_SUBPROCESS", "1")
    # The expr reaches into os.environ from the unrestricted child interpreter.
    # The assertion passes iff the key is ABSENT from the child's environment.
    case = _python_case("__import__('os').environ.get('ANTHROPIC_API_KEY') is None")
    resp = Response(case_id=case.id, text="ignored")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is True, "subprocess could read a stripped secret env var"


def test_subprocess_keeps_non_secret_env(monkeypatch):
    # Sanity: non-secret vars still reach the child (env is stripped, not empty).
    monkeypatch.setenv("PP_HARMLESS_MARKER", "present")
    monkeypatch.setenv("POLYGRAPH_ALLOW_SUBPROCESS", "1")
    case = _python_case(
        "__import__('os').environ.get('PP_HARMLESS_MARKER') == 'present'"
    )
    resp = Response(case_id=case.id, text="ignored")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is True


def test_secret_env_classifier():
    assert _is_secret_env("ANTHROPIC_API_KEY")
    assert _is_secret_env("OPENAI_API_KEY")
    assert _is_secret_env("POLYGRAPH_API_KEYS")
    assert _is_secret_env("POLYGRAPH_SIGNING_KEY")
    assert _is_secret_env("SOME_CUSTOM_API_KEY")
    assert _is_secret_env("github_token")  # case-insensitive
    assert _is_secret_env("DB_SECRET")
    assert not _is_secret_env("PATH")
    assert not _is_secret_env("HOME")


def test_minimal_env_excludes_known_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("POLYGRAPH_SIGNING_KEY", "x")
    monkeypatch.setenv("CUSTOM_TOKEN", "x")
    monkeypatch.setenv("HARMLESS", "ok")
    env = _minimal_subprocess_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "POLYGRAPH_SIGNING_KEY" not in env
    assert "CUSTOM_TOKEN" not in env
    assert env.get("HARMLESS") == "ok"


# ─── Edge cases ──────────────────────────────────────────────────────────────


def test_subprocess_missing_expr(monkeypatch):
    monkeypatch.setenv("POLYGRAPH_ALLOW_SUBPROCESS", "1")
    case = Case(prompt="x", assertions=[AssertionSpec(kind="python", options={})])
    resp = Response(case_id=case.id, text="x")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is False
    assert "needs options.expr" in r[0].detail


def test_subprocess_timeout(monkeypatch):
    monkeypatch.setenv("POLYGRAPH_ALLOW_SUBPROCESS", "1")
    case = Case(
        prompt="x",
        assertions=[
            AssertionSpec(
                kind="python",
                options={"expr": "__import__('time').sleep(5) or True", "timeout_s": 0.5},
            )
        ],
    )
    resp = Response(case_id=case.id, text="x")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is False
    assert "timed out" in r[0].detail


def test_subprocess_runtime_error_does_not_raise(monkeypatch):
    monkeypatch.setenv("POLYGRAPH_ALLOW_SUBPROCESS", "1")
    case = _python_case("1 / 0")
    resp = Response(case_id=case.id, text="x")
    r, _, _ = _run(score_assertions(case, resp, sandbox="subprocess"))
    assert r[0].passed is False
    assert "subprocess error" in r[0].detail
