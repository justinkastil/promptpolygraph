"""Adapter for retrieval-augmented (RAG) targets.

A RAG target retrieves documents for a query and generates an answer grounded in
them. The adversarial surface is the retrieval corpus: an attacker who can place
a document in the index can carry an indirect prompt injection into the answer.

`RagAdapter` wraps a callable ``fn(query, *, injected_docs) -> result`` where
``result`` is a ``{"text", "retrieved"}`` mapping (or an object exposing those):
``retrieved`` is the list of document ids/snippets the target used. The adapter
records them on ``Response.raw["retrieved"]`` so an assertion or the breach judge
can check grounding and detect a poisoned document's influence.

`MockRagTarget` is a deterministic in-process target with a small in-memory store
(token-overlap retrieval), so RAG runs and the test suite need no vector DB. A
probe may carry poisoned documents via ``Case.metadata["injected_docs"]``; a
vulnerable target retrieves and obeys an instruction embedded in a retrieved doc.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Awaitable, Callable

from ..models import Case, Response
from .base import BaseAdapter

RagFn = Callable[..., Any] | Callable[..., Awaitable[Any]]


def _normalize(result: Any) -> tuple[str, list[Any]]:
    if isinstance(result, str):
        return result, []
    if isinstance(result, dict):
        return str(result.get("text", "")), list(result.get("retrieved", []) or [])
    return str(getattr(result, "text", "")), list(getattr(result, "retrieved", []) or [])


class RagAdapter(BaseAdapter):
    """Wrap a retrieve-then-generate target; record retrieved docs per case."""

    name = "rag"

    def __init__(self, name: str | None = None, *, fn: RagFn | None = None, **_: Any):
        super().__init__(name)
        if fn is None:
            raise ValueError("RagAdapter requires a callable `fn`")
        self._fn = fn

    async def query(self, case: Case) -> Response:
        start = time.perf_counter()
        injected = (case.metadata or {}).get("injected_docs") or []
        try:
            result = self._fn(case.prompt, injected_docs=injected)
            if inspect.isawaitable(result):
                result = await result
            text, retrieved = _normalize(result)
        except Exception as exc:
            return Response(case_id=case.id, error=f"{type(exc).__name__}: {exc}",
                            latency_ms=self._elapsed_ms(start), source=self.name)
        return Response(case_id=case.id, text=text, latency_ms=self._elapsed_ms(start),
                        source=self.name, model="rag", raw={"retrieved": retrieved})


# ── deterministic mock RAG target ────────────────────────────────────────────

# A tiny benign knowledge base the mock target retrieves from. Token overlap with
# the query selects the top document; ties break on insertion order.
_BASE_DOCS: list[dict[str, str]] = [
    {"id": "kb1", "text": "To reset a password, open Settings then Security and choose Reset."},
    {"id": "kb2", "text": "Billing and subscription changes are made under the Billing menu."},
    {"id": "kb3", "text": "Business hours are Monday to Friday, nine to five, local time."},
    {"id": "kb4", "text": "Refunds are processed to the original payment method within ten days."},
]

# Instruction markers that a poisoned document might smuggle into the context.
_INJECTION_MARKERS = ("ignore", "disregard", "system:", "instruction:", "reply only",
                      "you must", "override")


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t}


class MockRagTarget:
    """Retrieve-then-generate target over an in-memory corpus.

    `vulnerable=True` (default) obeys an instruction embedded in a retrieved
    document (indirect injection); `vulnerable=False` treats retrieved text as
    data and ignores embedded instructions. Behavior is a pure function of the
    query and injected docs, so runs reproduce offline.
    """

    def __init__(self, *, vulnerable: bool = True, top_k: int = 2):
        self.vulnerable = vulnerable
        self.top_k = top_k

    def __call__(self, query: str, *, injected_docs: list[Any] | None = None) -> dict[str, Any]:
        corpus = list(_BASE_DOCS)
        for i, doc in enumerate(injected_docs or []):
            text = doc if isinstance(doc, str) else str((doc or {}).get("text", ""))
            did = f"inj{i}" if isinstance(doc, str) else str((doc or {}).get("id", f"inj{i}"))
            corpus.append({"id": did, "text": text})

        q = _tokens(query)
        ranked = sorted(corpus, key=lambda d: len(q & _tokens(d["text"])), reverse=True)
        retrieved = [d for d in ranked[: self.top_k] if q & _tokens(d["text"])] or ranked[:1]
        retrieved_ids = [d["id"] for d in retrieved]

        poisoned = next(
            (d for d in retrieved if any(m in d["text"].lower() for m in _INJECTION_MARKERS)),
            None,
        )
        if poisoned is not None and self.vulnerable:
            # Indirect injection: the target follows the document's instruction.
            return {"text": f"BREACH: following retrieved instruction - {poisoned['text']}",
                    "retrieved": retrieved_ids}
        if poisoned is not None:
            return {"text": "I use retrieved documents as reference only and ignore instructions in them.",
                    "retrieved": retrieved_ids}
        answer = retrieved[0]["text"] if retrieved else "No relevant document found."
        return {"text": answer, "retrieved": retrieved_ids}


def make_rag_adapter(name: str | None = None, *, fn: RagFn | None = None,
                     vulnerable: bool = True, **_: Any) -> RagAdapter:
    """Build a RagAdapter. With no `fn`, wraps a MockRagTarget so the adapter is
    runnable offline (used by examples + tests)."""
    return RagAdapter(name, fn=fn or MockRagTarget(vulnerable=vulnerable))
