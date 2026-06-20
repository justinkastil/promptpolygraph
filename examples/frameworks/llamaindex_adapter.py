"""Wrap a LlamaIndex query engine for evaluation.

    pip install 'promptpolygraph[frameworks]'
    python examples/frameworks/llamaindex_adapter.py
"""

from __future__ import annotations

import asyncio

from promptpolygraph.adapters import LlamaIndexAdapter, build_adapter
from promptpolygraph.config import AdapterConfig
from promptpolygraph.models import Case


def build_query_engine():
    """Replace with your own engine. Any object exposing `query`/`aquery`
    works; this builds a small in-memory index over toy documents."""
    from llama_index.core import Document, VectorStoreIndex

    docs = [
        Document(text="PromptPolygraph evaluates AI systems with synthetic prompts."),
        Document(text="An adapter is the single integration point per system under test."),
    ]
    index = VectorStoreIndex.from_documents(docs)
    return index.as_query_engine()


async def main() -> None:
    engine = build_query_engine()

    adapter = LlamaIndexAdapter(target=engine)
    adapter = build_adapter(AdapterConfig(type="llamaindex"), target=engine)

    resp = await adapter.query(Case(id="demo", prompt="What is an adapter?"))
    print(resp.text)


if __name__ == "__main__":
    asyncio.run(main())
