# LLM providers

PromptPolygraph talks to LLM backends through a single client interface. Pick a
backend with the `provider` field in your config (`llm.provider`) or
`--provider` on the CLI.

| Provider value             | Backend                              | Extra to install        |
|----------------------------|--------------------------------------|-------------------------|
| `anthropic` (default)      | Anthropic Messages API               | none (core dependency)  |
| `openai`                   | OpenAI Chat Completions              | none (uses httpx)       |
| `openai-compatible`        | Any OpenAI-compatible HTTP endpoint  | none (uses httpx)       |
| `ollama` / `vllm` / `lmstudio` / `local` | Local OpenAI-compatible server | none (uses httpx) |
| `litellm`                  | LiteLLM catch-all (~100 providers)   | `[litellm]`             |
| `bedrock`                  | AWS Bedrock (via LiteLLM)            | `[litellm]`             |
| `vertex` / `vertex_ai`     | Google Vertex AI (via LiteLLM)       | `[litellm]`             |
| `azure`                    | Azure OpenAI (via LiteLLM)           | `[litellm]`             |
| `gemini`                   | Google Gemini / AI Studio (via LiteLLM) | `[litellm]`          |
| `cohere`                   | Cohere (via LiteLLM)                 | `[litellm]`             |

Install the optional extra for the LiteLLM-routed providers:

```
pip install promptpolygraph[litellm]
```

## Anthropic

```
export ANTHROPIC_API_KEY=sk-ant-...
```

Provider `anthropic`. Default model `claude-opus-4-8`.

## OpenAI and OpenAI-compatible

```
export OPENAI_API_KEY=sk-...
```

Provider `openai`. For a non-OpenAI endpoint that speaks the same protocol, use
`provider: openai-compatible` and set `base_url`. Local servers (`ollama`,
`vllm`, `lmstudio`, `local`) need no key.

## LiteLLM catch-all

The `litellm` provider routes through `litellm.completion()` and reaches any
provider LiteLLM supports. Pass the fully prefixed model string LiteLLM expects:

```
provider: litellm
model: bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
```

The named cloud aliases below are conveniences: they prepend the LiteLLM prefix
for you when the model string has none, so `provider: gemini` + `model:
gemini-1.5-pro` is equivalent to `provider: litellm` + `model:
gemini/gemini-1.5-pro`.

Authentication for every LiteLLM-routed provider uses that cloud's own
environment variables, read by LiteLLM directly. PromptPolygraph does not manage
or inject these keys.

### AWS Bedrock (`bedrock`)

```
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION_NAME=us-east-1
# or use a named profile:
export AWS_PROFILE=my-profile
```

Model: `anthropic.claude-3-5-sonnet-20241022-v2:0` (the `bedrock/` prefix is
added for you when using `provider: bedrock`).

### Google Vertex AI (`vertex` / `vertex_ai`)

```
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export VERTEXAI_PROJECT=my-gcp-project
export VERTEXAI_LOCATION=us-central1
```

Model: `gemini-1.5-pro` (prefixed to `vertex_ai/gemini-1.5-pro`).

### Azure OpenAI (`azure`)

```
export AZURE_API_KEY=...
export AZURE_API_BASE=https://your-resource.openai.azure.com
export AZURE_API_VERSION=2024-02-15-preview
```

Model: your Azure deployment name (prefixed to `azure/<deployment>`).

### Google Gemini / AI Studio (`gemini`)

```
export GEMINI_API_KEY=...
```

Model: `gemini-1.5-pro` (prefixed to `gemini/gemini-1.5-pro`).

### Cohere (`cohere`)

```
export COHERE_API_KEY=...
```

Model: `command-r-plus` (prefixed to `cohere/command-r-plus`).

## Sampling parameters

Some models reject sampling parameters (`temperature`). The client suppresses
`temperature` for those automatically; for all other models the configured
temperature is forwarded.
