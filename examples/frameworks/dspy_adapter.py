"""Wrap a DSPy program for evaluation.

    pip install 'promptpolygraph[frameworks]'
    python examples/frameworks/dspy_adapter.py
"""

from __future__ import annotations

import asyncio

from promptpolygraph.adapters import DSPyAdapter, build_adapter
from promptpolygraph.config import AdapterConfig
from promptpolygraph.models import Case


def build_program():
    """Replace with your own (optionally compiled) program. A DSPy module is
    callable; this one answers a single question field."""
    import dspy

    # Configure a backing LM once, e.g.:
    #   dspy.settings.configure(lm=dspy.LM("openai/gpt-4o-mini"))
    return dspy.Predict("question -> answer")


async def main() -> None:
    program = build_program()

    # The program is called as program(question=prompt). Override the input
    # field name via `input_field` if your signature differs.
    adapter = DSPyAdapter(target=program, input_field="question")
    adapter = build_adapter(
        AdapterConfig(type="dspy", options={"input_field": "question"}),
        target=program,
    )

    resp = await adapter.query(Case(id="demo", prompt="What is regression testing?"))
    print(resp.text)


if __name__ == "__main__":
    asyncio.run(main())
