# Quickstart

No API key, no setup. Install, then run the bundled offline mock demo.

## Install

```bash
pip install promptpolygraph
```

From a source checkout, install with the dev extras:

```bash
pip install -e ".[dev]"            # core + test deps
pip install -e ".[dev,llm]"        # + OpenAI-compatible adapter
pip install -e ".[dev,redteam]"    # + OSS-grounded red-team sources
```

Requires Python 3.10+. The red-team engine and Arena work with no extras; the
`[redteam]` extra only lights up the external OSS sources.

## Run the offline demo

This runs a fixed corpus through a built-in demo target, scores it, runs the
persona and forensic audit, and writes reports under `polygraph_out/`. No API
key is needed in `--mock` mode.

```bash
polygraph all --config examples/everyday_assistant/config.yaml --mock --format md,html,docx,pdf
```

With an `ANTHROPIC_API_KEY` set and a real adapter configured, drop `--mock`.

## Bundled example packs

Each pack is a self-contained `config + corpus + rubric + personas`:

- `examples/everyday_assistant/` — a neutral general-purpose assistant.
- `examples/support_bot/` — a customer-support assistant for a fictional SaaS.
- `examples/clinical_trials/` — a domain pack for a protocol assistant.

Copy one as a starting point, or generate a tailored pack with `polygraph tune`.

## Point an adapter at your system

The adapter is the only thing that changes per target. Set it in `config.yaml`:

```yaml
# HTTP / REST
adapter:
  type: http
  options:
    url: https://api.example.com/chat
    method: POST
    headers: { Authorization: "Bearer ${API_KEY}" }   # ${VAR} reads the env
    body_template: { message: "{{prompt}}" }           # {{prompt}} {{category}} {{id}}
    response_path: "reply.text"                         # JMESPath into the JSON response

# LLM chat (OpenAI / Anthropic / OpenAI-compatible; openai needs the [llm] extra)
adapter:
  type: llm
  options: { provider: anthropic, model: claude-opus-4-8, system: "You are ...", max_tokens: 512 }
```

For anything exotic, implement `async def query(self, case) -> Response` and
pass an in-process callable with `--callable mymodule:my_fn`.

## Run on local or open models

The grader/judge, audit agents, and corpus generation can run against any
OpenAI-compatible endpoint, so the whole eval can run locally with no API key:

```yaml
llm:
  provider: ollama          # anthropic (default) | openai | ollama | vllm | lmstudio | openai-compatible
  base_url: http://localhost:11434/v1
  model: llama3.1
```

## Next steps

- [CLI](cli.md) — the full command reference.
- [Validation](VALIDATION.md) — the regenerable validation package.
- [CI](CI.md) — running PromptPolygraph as a pipeline gate.
