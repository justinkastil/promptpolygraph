"""Wrap a LangChain Runnable/Chain for evaluation.

    pip install 'promptpolygraph[frameworks]'
    python examples/frameworks/langchain_adapter.py
"""

from __future__ import annotations

import asyncio

from promptpolygraph.adapters import LangChainAdapter, build_adapter
from promptpolygraph.config import AdapterConfig
from promptpolygraph.models import Case


def build_chain():
    """Replace with your own chain. Any Runnable exposing `invoke`/`ainvoke`
    works; this minimal example uses a prompt | model | parser pipeline."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    # Bring your own model, e.g. langchain_openai.ChatOpenAI(model="gpt-4o-mini").
    from langchain_openai import ChatOpenAI

    prompt = ChatPromptTemplate.from_messages(
        [("system", "You are a concise assistant."), ("human", "{input}")]
    )
    return prompt | ChatOpenAI(model="gpt-4o-mini", temperature=0) | StrOutputParser()


async def main() -> None:
    chain = build_chain()

    # Direct construction.
    adapter = LangChainAdapter(target=chain)

    # Or via config/CLI plumbing; the live object is injected as `target`.
    adapter = build_adapter(AdapterConfig(type="langchain"), target=chain)

    resp = await adapter.query(Case(id="demo", prompt="What is a unit test?"))
    print(resp.text)


if __name__ == "__main__":
    asyncio.run(main())
