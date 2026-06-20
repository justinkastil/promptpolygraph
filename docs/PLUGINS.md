# Plugins

PromptPolygraph discovers third-party extensions through
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/).
Any pip-installed package can register an adapter, attack source, judge, or
report format by declaring an entry point under one of these groups, with no
fork or monkeypatch required:

| Group                       | Extends                              | Wired today          |
| --------------------------- | ------------------------------------ | -------------------- |
| `promptpolygraph.adapters`  | adapter `type` -> adapter factory    | yes (`build_adapter`)|
| `promptpolygraph.sources`   | red-team source name -> factory      | yes (source registry)|
| `promptpolygraph.judges`    | judge name -> factory                | discovery / listing  |
| `promptpolygraph.reporters` | report format -> renderer            | discovery / listing  |

Built-in adapters (`http`, `llm`, `demo`, `callable`) and the built-in `catalog`
source always take precedence; a plugin cannot shadow them. A plugin whose
import fails is skipped, never fatal, so one broken extension cannot take down
the harness.

List everything the current environment exposes:

```console
$ polygraph plugins list
adapters
  http (built-in)
  llm (built-in)
  demo (built-in)
  callable (built-in)
  echo -> my_polygraph_echo:EchoAdapter (my-polygraph-echo)
sources
  catalog (built-in)
judges
  (none)
reporters
  (none)
```

## Minimal example: an adapter plugin

A plugin is an ordinary package. The adapter is any class or factory callable
that accepts `name=` plus the config's `options` as keyword arguments and
satisfies the adapter protocol (an async `query(case) -> Response`).

`my_polygraph_echo.py`:

```python
from promptpolygraph.adapters.base import BaseAdapter
from promptpolygraph.models import Case, Response


class EchoAdapter(BaseAdapter):
    """Returns the prompt back, optionally prefixed. Used as a wiring example."""

    def __init__(self, *, name: str = "echo", prefix: str = "", **_: object) -> None:
        super().__init__(name=name)
        self.prefix = prefix

    async def query(self, case: Case) -> Response:
        return Response(text=f"{self.prefix}{case.prompt}")
```

`pyproject.toml`:

```toml
[project]
name = "my-polygraph-echo"
version = "0.1.0"
dependencies = ["promptpolygraph"]

[project.entry-points."promptpolygraph.adapters"]
echo = "my_polygraph_echo:EchoAdapter"
```

After `pip install -e .`, the new type resolves like any built-in. Options under
`adapter.options` are passed straight to the constructor:

```yaml
# config.yaml
adapter:
  type: echo
  options:
    prefix: "echoed: "
```

```console
$ polygraph plugins list | grep echo
  echo -> my_polygraph_echo:EchoAdapter (my-polygraph-echo)
```

## Attack-source plugins

An attack source plugin declares a factory under `promptpolygraph.sources`. The
factory is called with keyword arguments and must return an object implementing
the `AttackSource` protocol (`available()` and an async `generate(...)`). See
`promptpolygraph.redteam.sources.base` for the protocol. Built-in source names
are reserved; a plugin reusing one is ignored.

```toml
[project.entry-points."promptpolygraph.sources"]
mysource = "my_polygraph_source:make_source"
```

## Judges and reporters

The `promptpolygraph.judges` and `promptpolygraph.reporters` groups are reserved
and surfaced by `polygraph plugins list` for forward compatibility. They are not
yet consulted at resolution time; declaring them now is harmless and keeps a
plugin's manifest stable as that wiring lands.
