# PromptPolygraph

**Synthetic-prompt evaluation and persona-audit harness for web and API AI systems.**

PromptPolygraph pushes thousands of synthetic prompts through any web/API/LLM system, scores the
responses against a pluggable rubric (plus cheap deterministic assertions and an optional multi-judge
ensemble), reacts to them through a panel of personas, traces low scores with a forensic audit, and
renders the result as a markdown / docx / pdf / html report.

It is **local-first and cloud-agnostic**: one process, an async concurrency pool, and a SQLite store —
runs on a laptop, a CI runner, or a container. No work queue, no database server, nothing to deploy. It
also ships a **deployable API + worker** (Postgres-backed, Dockerized) for multi-user, team-scale use;
see the [Service](SERVICE.md) guide.

## Why

Evaluating an AI system well means more than a single accuracy number. PromptPolygraph combines:

- **Synthetic corpora** — a fixed deterministic set for clean run-over-run baselining, or LLM-generated
  *varied* / *adversarial* probes, with dials for quantity, categories, difficulty, and seed.
- **Adapters** — one small class (`async def query(case) -> Response`) per system under test. Ships an
  HTTP/REST adapter, an LLM-chat adapter, and an in-process callable adapter.
- **Layered scoring** — deterministic assertions (contains / regex / json-schema / latency / semantic
  similarity / custom Python), with weights, per-test thresholds, and named + derived metrics, then an
  LLM rubric scorer with a multi-judge ensemble and inter-judge agreement.
- **Persona panel** — a pool of distinct individuals react to the real responses (trust, usefulness,
  clarity, would-return), reconciled against the rubric.
- **Forensic audit** — per-category agents trace low scores to failure modes and emit a concrete
  suggested fix for systems whose source you provide.
- **Comparison and trends** — comparability-gated N-run comparison, per-dimension trends, and regression
  detection vs a pinned or rolling baseline, with statistical significance.
- **Visuals and reports** — a local dashboard and presentation-grade markdown / docx / pdf / html
  reports with inline charts.

## Get started

- [Quickstart](quickstart.md) — install and run the offline demo in 30 seconds.
- [CLI](cli.md) — the command reference.
- [Architecture](ARCHITECTURE.md) — how the pipeline fits together.
- [Threat model](THREAT_MODEL.md) — what this tool does and does not protect.
- [API Reference](reference.md) — the public Python API.
