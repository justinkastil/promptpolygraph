"""Tests for optional streaming evaluation (issue #46).

Covers the additive Response.tokens_streamed field, the streaming-aware
assertion kinds (stream_contains / first_n_tokens), the LLM adapter's streaming
path against deterministic mock clients (no network), and the new
streaming_evasion technique. The non-streaming path must stay unchanged.
"""

from __future__ import annotations

import asyncio

from promptpolygraph.adapters.llm import LLMAdapter
from promptpolygraph.analyze.assertions import evaluate_assertions, score_assertions
from promptpolygraph.models import AssertionSpec, Case, Response
from promptpolygraph.redteam import catalog


def _run(coro):
    return asyncio.run(coro)


# ─── Mock streaming clients (offline, deterministic) ─────────────────────────


class _MockUsage:
    def __init__(self, tin: int, tout: int):
        self.input_tokens = tin
        self.output_tokens = tout
        self.prompt_tokens = tin
        self.completion_tokens = tout


class _MockAnthropicStreamCtx:
    """Stand-in for client.messages.stream(...)'s async context manager."""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def _gen():
            for c in self._chunks:
                yield c

        return _gen()

    async def get_final_message(self):
        class _Msg:
            usage = _MockUsage(11, 22)

        return _Msg()


class _MockAnthropicMessages:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    def stream(self, **_):
        return _MockAnthropicStreamCtx(self._chunks)


class _MockAnthropicClient:
    def __init__(self, chunks: list[str]):
        self.messages = _MockAnthropicMessages(chunks)


class _MockOpenAIEvent:
    def __init__(self, content: str | None, usage=None):
        if content is None:
            self.choices = []
        else:
            delta = type("Delta", (), {"content": content})()
            self.choices = [type("Choice", (), {"delta": delta})()]
        self.usage = usage


class _MockOpenAIStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        async def _gen():
            for e in self._events:
                yield e

        return _gen()


class _MockOpenAICompletions:
    def __init__(self, events):
        self._events = events

    async def create(self, **_):
        return _MockOpenAIStream(self._events)


class _MockOpenAIClient:
    def __init__(self, events):
        self.chat = type("Chat", (), {"completions": _MockOpenAICompletions(events)})()


# ─── Response.tokens_streamed round-trip ─────────────────────────────────────


def test_tokens_streamed_default_empty_and_backward_compatible():
    # Old records carry no tokens_streamed; the field defaults to empty.
    r = Response.model_validate({"case_id": "c1", "text": "hi"})
    assert r.tokens_streamed == []


def test_tokens_streamed_round_trips():
    r = Response(case_id="c1", text="hello world", tokens_streamed=["hel", "lo ", "world"])
    dumped = r.model_dump()
    again = Response.model_validate(dumped)
    assert again.tokens_streamed == ["hel", "lo ", "world"]
    assert "".join(again.tokens_streamed) == "hello world"


# ─── Streaming-aware assertions ──────────────────────────────────────────────


def test_stream_contains_passes_and_fails():
    resp = Response(case_id="c1", text="abc", tokens_streamed=["ab", "cd", "ef"])
    ok = Case(prompt="x", assertions=[AssertionSpec(kind="stream_contains", value="cd")])
    bad = Case(prompt="x", assertions=[AssertionSpec(kind="stream_contains", value="zz")])
    res_ok, passed_ok, _ = _run(score_assertions(ok, resp))
    res_bad, passed_bad, _ = _run(score_assertions(bad, resp))
    assert passed_ok and res_ok[0].passed
    assert not passed_bad and not res_bad[0].passed


def test_first_n_tokens_scopes_to_early_chunks():
    # "secret" arrives only in the 3rd chunk; first_n=2 must not see it.
    resp = Response(case_id="c1", text="hi there secret", tokens_streamed=["hi ", "there ", "secret"])
    early_leak = Case(
        prompt="x",
        assertions=[AssertionSpec(kind="first_n_tokens", value="secret", options={"first_n": 2})],
    )
    full = Case(
        prompt="x",
        assertions=[AssertionSpec(kind="stream_contains", value="secret")],
    )
    _, leaked_early, _ = _run(score_assertions(early_leak, resp))
    _, in_full_stream, _ = _run(score_assertions(full, resp))
    assert not leaked_early
    assert in_full_stream


def test_stream_assertion_falls_back_to_text_without_stream():
    # No recorded stream: a stream assertion degrades to a content check.
    resp = Response(case_id="c1", text="plain answer", tokens_streamed=[])
    case = Case(prompt="x", assertions=[AssertionSpec(kind="stream_contains", value="answer")])
    _, passed, _ = _run(score_assertions(case, resp))
    assert passed


# ─── Streaming adapter path (mock clients) ───────────────────────────────────


def test_anthropic_stream_assembles_text_from_chunks():
    adapter = LLMAdapter(provider="anthropic", model="claude-opus-4-8", stream=True)
    adapter._client = _MockAnthropicClient(["Hel", "lo, ", "world"])
    resp = _run(adapter.query(Case(prompt="say hi")))
    assert resp.error is None
    assert resp.text == "Hello, world"
    assert resp.tokens_streamed == ["Hel", "lo, ", "world"]
    assert resp.tokens_in == 11 and resp.tokens_out == 22


def test_openai_stream_assembles_text_from_chunks():
    events = [
        _MockOpenAIEvent("Hel"),
        _MockOpenAIEvent("lo"),
        _MockOpenAIEvent(None),  # keep-alive event with no choices
        _MockOpenAIEvent("!", usage=_MockUsage(3, 4)),
    ]
    adapter = LLMAdapter(provider="openai", model="gpt-4o-mini", stream=True)
    adapter._client = _MockOpenAIClient(events)
    resp = _run(adapter.query(Case(prompt="say hi")))
    assert resp.error is None
    assert resp.text == "Hello!"
    assert resp.tokens_streamed == ["Hel", "lo", "!"]
    assert resp.tokens_in == 3 and resp.tokens_out == 4


def test_non_streaming_path_unchanged():
    # Default adapter does not stream; tokens_streamed stays empty.
    class _Msg:
        content = [type("Block", (), {"text": "non-stream reply"})()]
        usage = _MockUsage(5, 6)

    class _Messages:
        async def create(self, **_):
            return _Msg()

    adapter = LLMAdapter(provider="anthropic", model="claude-opus-4-8")
    assert adapter._stream is False
    adapter._client = type("C", (), {"messages": _Messages()})()
    resp = _run(adapter.query(Case(prompt="hi")))
    assert resp.text == "non-stream reply"
    assert resp.tokens_streamed == []


# ─── Catalog technique + reference lock ──────────────────────────────────────


def test_streaming_evasion_technique_exists_and_tagged():
    t = next((x for x in catalog.TECHNIQUES if x.id == "streaming_evasion"), None)
    assert t is not None
    assert t.owasp and t.atlas
    assert t.atlas.startswith("AML.T")
    assert t.seeds


def test_reference_lock_check_passes():
    from promptpolygraph.provenance import check_reference_integrity

    assert check_reference_integrity()["ok"] is True


# ─── Unknown-kind handling preserved ─────────────────────────────────────────


def test_unknown_kind_still_handled_gracefully():
    resp = Response(case_id="c1", text="x")
    case = Case(prompt="x", assertions=[AssertionSpec(kind="not_a_real_kind")])
    results, passed = evaluate_assertions(case, resp)
    assert not passed and not results[0].passed
