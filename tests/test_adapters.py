from __future__ import annotations

import httpx
import pytest

from promptpolygraph.adapters import CallableAdapter, HTTPAdapter
from promptpolygraph.models import Case


async def test_callable_adapter_plain_and_dict():
    a = CallableAdapter(fn=lambda p: f"got:{p}")
    r = await a.query(Case(prompt="hi"))
    assert r.text == "got:hi" and r.latency_ms is not None

    def rich(case: Case) -> dict:
        return {"text": "x", "tokens_out": 7, "model": "m"}

    b = CallableAdapter(fn=rich)
    r2 = await b.query(Case(prompt="hi"))
    assert r2.text == "x" and r2.tokens_out == 7 and r2.model == "m"


async def test_callable_adapter_catches_errors():
    def boom(p: str) -> str:
        raise ValueError("nope")

    a = CallableAdapter(fn=boom)
    r = await a.query(Case(prompt="hi"))
    assert r.error and "ValueError" in r.error


async def test_http_adapter_request_and_extraction():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"reply": {"text": "pong"}, "usage": {"out": 12}})

    a = HTTPAdapter(
        url="https://x.test/chat",
        headers={"Authorization": "Bearer T"},
        body_template={"message": "{{prompt}}", "cat": "{{category}}"},
        response_path="reply.text",
        tokens_out_path="usage.out",
    )
    a._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = await a.query(Case(prompt="ping", category="accuracy"))
    assert r.text == "pong" and r.tokens_out == 12
    assert "ping" in seen["body"] and "accuracy" in seen["body"]
    assert seen["auth"] == "Bearer T"
    await a.aclose()


async def test_http_adapter_error_becomes_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    a = HTTPAdapter(url="https://x.test/chat")
    a._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = await a.query(Case(prompt="ping"))
    assert r.error is not None
    await a.aclose()
