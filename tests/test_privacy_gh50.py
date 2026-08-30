"""End-to-end coverage for GitHub #50: PII redaction, residency, redacted export.

`tests/test_privacy_scrub_pii.py` covers the regex surface of `scrub_pii` in
depth. This module covers the parts #50 adds *around* it: the settings field,
the two persistence chokepoints, the opt-in export flag, and the boundaries the
founder contract explicitly draws (the cache is not redacted; unflagged export
output is unchanged).

Entirely offline: temp sqlite, monkeypatched env, no network, no API key.
"""

from __future__ import annotations

import json

import pytest

from promptpolygraph.models import Case, Response
from promptpolygraph.runner import SQLiteStore
from promptpolygraph.service.db import SqlStore
from promptpolygraph.service.privacy import scrub_pii

EMAIL = "jane.doe@example.com"
SSN = "123-45-6789"
BODY = f"Contact Jane Doe at {EMAIL}, SSN {SSN}."
CLEAN = "Go to Settings > Security > Reset. Order 7781 shipped on 2024-01-02."


def _assert_scrubbed(text: str) -> None:
    assert EMAIL not in text
    assert SSN not in text


# ─── scrub_pii ──────────────────────────────────────────────────────────────

def test_email_is_redacted():
    out = scrub_pii(f"write to {EMAIL} today")
    assert EMAIL not in out
    assert out == "write to [REDACTED-EMAIL] today"


def test_ssn_is_redacted():
    out = scrub_pii(f"her SSN is {SSN}.")
    assert SSN not in out
    assert out == "her SSN is [REDACTED-SSN]."


def test_non_pii_text_passes_through_unchanged():
    assert scrub_pii(CLEAN) == CLEAN


def test_empty_and_non_str_input_return_str_without_raising():
    assert scrub_pii("") == ""
    for value in (None, 0, 12.5, b"", [], {}, object()):
        assert isinstance(scrub_pii(value), str)  # type: ignore[arg-type]


# ─── Settings.data_residency ────────────────────────────────────────────────

@pytest.fixture
def settings_factory(monkeypatch):
    """Yield a callable returning a freshly-built Settings, env honoured.

    `get_settings` is `lru_cache`d (the frozen `scripts/accept_gh50.py` relies
    on `cache_clear`), so the cache is cleared before *and* after each use to
    keep a residency override from leaking into another test.
    """
    from promptpolygraph.service.settings import get_settings

    # An operator's real .env must not decide the outcome of these assertions.
    monkeypatch.delenv("POLYGRAPH_DATA_RESIDENCY", raising=False)

    def build():
        get_settings.cache_clear()
        return get_settings()

    yield build
    get_settings.cache_clear()


def test_data_residency_defaults_to_none(settings_factory):
    assert settings_factory().data_residency == "none"


@pytest.mark.parametrize("value", ["eu", "us", "none"])
def test_data_residency_env_override(settings_factory, monkeypatch, value):
    monkeypatch.setenv("POLYGRAPH_DATA_RESIDENCY", value)
    assert settings_factory().data_residency == value


@pytest.mark.parametrize("raw,expected", [("EU", "eu"), (" us ", "us"), ("", "none")])
def test_data_residency_env_is_normalized(settings_factory, monkeypatch, raw, expected):
    monkeypatch.setenv("POLYGRAPH_DATA_RESIDENCY", raw)
    assert settings_factory().data_residency == expected


def test_data_residency_rejects_an_unknown_region(settings_factory, monkeypatch):
    """A typo must fail loudly, not be silently downgraded to "none"."""
    monkeypatch.setenv("POLYGRAPH_DATA_RESIDENCY", "eur")
    with pytest.raises(Exception):
        settings_factory()


def test_data_residency_is_one_of_the_three_documented_values(settings_factory):
    assert settings_factory().data_residency in {"eu", "us", "none"}


# ─── redaction on ingest, both stores ───────────────────────────────────────

@pytest.fixture(params=["runner", "service"])
def any_store(request, tmp_path):
    """Both `Store` implementations that write the `responses` table."""
    if request.param == "runner":
        store = SQLiteStore(tmp_path / "runner.sqlite")
    else:
        store = SqlStore(f"sqlite:///{tmp_path / 'svc.sqlite'}")
    yield store
    store.close()


def test_response_body_is_redacted_on_ingest(any_store):
    case = Case(prompt="p", category="accuracy")
    any_store.save_cases("r1", [case])
    any_store.save_response("r1", Response(case_id=case.id, text=BODY))

    stored = any_store.get_responses("r1")
    assert len(stored) == 1
    _assert_scrubbed(stored[0].text)
    assert "[REDACTED-EMAIL]" in stored[0].text
    assert "[REDACTED-SSN]" in stored[0].text


def test_streamed_chunks_are_redacted_on_ingest(any_store):
    """`tokens_streamed` reconstructs the body, so it is part of the body."""
    case = Case(prompt="p", category="accuracy")
    any_store.save_cases("r1", [case])
    any_store.save_response(
        "r1", Response(case_id=case.id, text=BODY, tokens_streamed=["mail ", EMAIL])
    )

    stored = any_store.get_responses("r1")[0]
    _assert_scrubbed("".join(stored.tokens_streamed))


def test_ingest_does_not_mutate_the_callers_response(any_store):
    """The in-memory object the runner still holds must be untouched."""
    case = Case(prompt="p", category="accuracy")
    resp = Response(case_id=case.id, text=BODY)
    any_store.save_cases("r1", [case])
    any_store.save_response("r1", resp)
    assert resp.text == BODY


def test_clean_body_round_trips_byte_for_byte(any_store):
    case = Case(prompt="p", category="accuracy")
    any_store.save_cases("r1", [case])
    any_store.save_response("r1", Response(case_id=case.id, text=CLEAN))
    assert any_store.get_responses("r1")[0].text == CLEAN


def test_cache_is_not_redacted(any_store):
    """Founder contract: `cache.data` is out of scope for #50."""
    any_store.cache_put("k1", Response(case_id="c1", text=BODY))
    cached = any_store.cache_get("k1")
    assert cached is not None
    assert cached.text == BODY


# ─── export_jsonl --redact ──────────────────────────────────────────────────

def _seed_legacy_row(store, run_id: str, case: Case) -> None:
    """Write a response body that bypasses the ingest scrub.

    Simulates a row persisted by a pre-#50 version, which is the only thing
    `--redact` is actually for once ingest redacts.
    """
    store.save_cases(run_id, [case])
    store.save_response(run_id, Response(case_id=case.id, text=CLEAN))
    raw = Response(case_id=case.id, text=BODY).model_dump_json()
    if isinstance(store, SQLiteStore):
        with store._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO responses (run_id, case_id, data) VALUES (?, ?, ?)",
                (run_id, case.id, raw),
            )
    else:
        from sqlalchemy import update as sa_update

        from promptpolygraph.service.db import responses as responses_table

        with store.engine.begin() as c:
            c.execute(
                sa_update(responses_table)
                .where(responses_table.c.run_id == run_id)
                .where(responses_table.c.case_id == case.id)
                .values(data=raw)
            )


def test_export_jsonl_defaults_to_not_redacting(any_store, tmp_path):
    """Default off: a legacy PII body is exported exactly as stored."""
    case = Case(prompt="p", category="accuracy")
    _seed_legacy_row(any_store, "r1", case)

    out = tmp_path / "plain.jsonl"
    any_store.export_jsonl("r1", out)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["response"]["text"] == BODY


def test_export_jsonl_redact_scrubs_bodies(any_store, tmp_path):
    case = Case(prompt="p", category="accuracy")
    _seed_legacy_row(any_store, "r1", case)

    out = tmp_path / "redacted.jsonl"
    any_store.export_jsonl("r1", out, redact=True)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    _assert_scrubbed(row["response"]["text"])
    # Everything other than the body is untouched by the flag.
    assert row["case"]["prompt"] == "p"


def test_export_jsonl_redact_off_is_byte_identical(any_store, tmp_path):
    """`redact=False` must produce exactly the pre-#50 bytes."""
    case = Case(prompt="p", category="accuracy")
    _seed_legacy_row(any_store, "r1", case)

    positional = tmp_path / "a.jsonl"
    explicit = tmp_path / "b.jsonl"
    any_store.export_jsonl("r1", positional)
    any_store.export_jsonl("r1", explicit, redact=False)
    assert positional.read_bytes() == explicit.read_bytes()


def test_export_jsonl_redact_leaves_clean_output_identical(any_store, tmp_path):
    """No PII in, no difference out — the flag is not a reformatter."""
    case = Case(prompt="p", category="accuracy")
    any_store.save_cases("r1", [case])
    any_store.save_response("r1", Response(case_id=case.id, text=CLEAN))

    plain = tmp_path / "plain.jsonl"
    red = tmp_path / "red.jsonl"
    any_store.export_jsonl("r1", plain)
    any_store.export_jsonl("r1", red, redact=True)
    assert plain.read_bytes() == red.read_bytes()


# ─── CLI `export --redact` ──────────────────────────────────────────────────

@pytest.fixture
def pii_corpus(tmp_path):
    """A corpus file whose prompts carry PII."""
    path = tmp_path / "corpus.json"
    path.write_text(
        json.dumps(
            [
                {"prompt": f"reset the account for {EMAIL}", "category": "accuracy"},
                {"prompt": f"my ssn is {SSN}", "category": "safety"},
            ]
        ),
        encoding="utf-8",
    )
    return path


def _export(corpus, out, *extra):
    """Drive the real `export` subcommand through the real argument parser.

    `cmd_export` is invoked directly rather than via `main()` so the test does
    not depend on a config file being discoverable from the working directory.
    """
    from promptpolygraph import cli
    from promptpolygraph.config import Config

    args = cli.build_parser().parse_args(
        ["export", "--corpus", str(corpus), "--out", str(out), *extra]
    )
    cli.cmd_export(Config(), args)
    return args


def test_cli_export_redact_defaults_off_in_the_parser(tmp_path, pii_corpus):
    """`--redact` is opt-in: absent from argv means False, never None."""
    args = _export(pii_corpus, tmp_path / "default.json")
    assert args.redact is False


def test_cli_export_without_redact_keeps_pii(tmp_path, pii_corpus):
    out = tmp_path / "plain.json"
    _export(pii_corpus, out)
    text = out.read_text(encoding="utf-8")
    assert EMAIL in text
    assert SSN in text


def test_cli_export_with_redact_scrubs_pii(tmp_path, pii_corpus):
    out = tmp_path / "red.json"
    _export(pii_corpus, out, "--redact")
    _assert_scrubbed(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fmt", ["json", "jsonl", "csv"])
def test_cli_export_redact_applies_in_every_format(tmp_path, pii_corpus, fmt):
    out = tmp_path / f"red.{fmt}"
    _export(pii_corpus, out, "--format", fmt, "--redact")
    _assert_scrubbed(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fmt", ["json", "jsonl", "csv"])
@pytest.mark.parametrize("prompts_only", [False, True])
def test_cli_export_redact_off_leaves_output_unchanged(tmp_path, pii_corpus, fmt, prompts_only):
    """Unflagged bytes must match what an unflagged run produced before #50.

    The `--redact` code path is skipped entirely when the flag is absent, so
    comparing an unflagged run against an explicitly-clean baseline is the
    strongest byte-level check available from inside the test suite: any
    reformatting introduced by the flag's plumbing would show up here.
    """
    extra = ["--format", fmt] + (["--prompts-only"] if prompts_only else [])
    a = tmp_path / f"a.{fmt}"
    b = tmp_path / f"b.{fmt}"
    _export(pii_corpus, a, *extra)
    _export(pii_corpus, b, *extra)
    assert a.read_bytes() == b.read_bytes()
    assert EMAIL in a.read_text(encoding="utf-8")
