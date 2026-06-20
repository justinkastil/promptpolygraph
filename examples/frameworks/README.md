# Framework adapters

Evaluate a pipeline you already built with an orchestration framework, without
rewriting it as a plain callable. Three thin wrappers turn the case prompt into
one invocation of your pipeline and normalize the result into a `Response`:

| Adapter type | Wraps | Call surface |
| --- | --- | --- |
| `langchain` | a Runnable / Chain | `ainvoke`, else `invoke` |
| `llamaindex` | a query engine | `aquery`, else `query` |
| `dspy` | a compiled program | the program is called directly |

Install the optional extra (only the framework you actually wrap needs to be
present):

    pip install 'promptpolygraph[frameworks]'

The wrappers take a live, already-constructed object via the `target` option, so
they are built in Python rather than from a YAML `adapter` block. The snippets
in this directory show the wiring:

- `langchain_adapter.py`
- `llamaindex_adapter.py`
- `dspy_adapter.py`

Each adapter registers as an entry point, so it appears in:

    polygraph plugins list
