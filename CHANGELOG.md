# Changelog

All notable changes to PromptPolygraph are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.1] - 2026-06-11

### Added
- **Corpus export in the dashboard** — a run's prompt corpus downloads as JSON,
  JSONL, or CSV from the run detail view (the UI face of `polygraph export`),
  with a `prompts_only` option. New `GET /api/runs/{id}/corpus` endpoint.
- **Persona-panel export in the studio** — saved persona panels download as YAML
  from the Persona studio. New `GET /api/personas/files/download` endpoint,
  bounded to the studio's saved files + bundled example panels (no arbitrary
  file reads).

## [0.5.0] - 2026-06-11

### Added
- **Red-team engine + live Arena** — a new `polygraph redteam` command and a
  realtime multi-agent Arena (attacker agents on the rails, the target in the
  centre, green/red breach accretion, drill-down to the mitigation). Streams
  over **SSE** in the local dashboard and **WebSocket** in the service. Runs
  fully offline in mock mode (deterministic probes + verdicts + simulated
  thinking stream) so the Arena demos with zero tokens.
- **Preconfigured attacker teams (profiles)** — `all_frontier` (the
  out-of-the-box default; every strategy on a frontier model, each agent a
  distinct persona + temperature), `multi_frontier` (mixed frontier vendors),
  `mixed` (local open models + frontier), `local_swarm` (100% offline),
  `pressure`, `quick`, and **`deep`** (adaptive smart multi-turn).
- **Technique catalog** — attackers seed + mutate from a catalog of known,
  standards-mapped techniques (OWASP Top-10 for LLM Apps + MITRE ATLAS) rather
  than improvising from a blank slate.
- **OSS-grounded attack sources** — pluggable probe sources that flow through
  the same target → breach-judge loop and into the report + Arena, attributed
  to their source: a built-in `catalog` source (no deps), plus optional
  `garak`, `pyrit`, and `deepteam` integrations and on-demand dataset loaders
  (`dataset:advbench`, `dataset:harmbench`, `dataset:jailbreakbench`). Install
  with the `[redteam]` extra; each source registers only when its dependency
  imports. Select with `--sources` or `redteam.sources` in config.
- **Smart multi-turn strategies** — PAIR (iterative refinement against the
  target's refusal), Crescendo (gradual escalation), and TAP (tree-of-attacks
  candidates) replace naive escalation when an attacker's `mode` is set.
- **Converter layer** — probe transforms (base64, rot13, leetspeak, reverse,
  unicode-confusable, payload-split, roleplay-wrap, whitespace-pad) and
  **many-shot** prefixing, selectable per attacker via `converter`.
- **Llama-Guard breach judge** — `--guard` scores breaches with a
  Llama-Guard-style safety classifier (MLCommons S1–S14 hazard taxonomy) on a
  local model, as an alternative to the LLM-reviewer judge.
- **ASR + OWASP coverage in the report** — attack-success-rate headline, an
  OWASP LLM Top-10 coverage table (tested vs breached), and per-vulnerability
  OWASP + MITRE ATLAS tags, across the Markdown, HTML, and JSON renderers.
- **Provenance-labelled local model roster** + Ollama/HuggingFace pull scripts
  and hardware guidance (Mac Studio / NVIDIA DGX Spark / cloud / Docker) for
  running attacker/judge models locally.

## [0.4.1] - 2026-06-11

### Added
- **Pluggable judge/audit/generation backend** — the grader, audit agents, and
  corpus generation can now run against any OpenAI-compatible endpoint
  (**Ollama**, vLLM, LM Studio, OpenAI), not just Anthropic. Configure via
  `llm: {provider: ollama, base_url: ...}` + `model: <name>`. Local providers
  need no API key, so the **whole eval can run 100% locally on open models**.
  Uses httpx (a core dep) — no extra packages required for the local path.
- The `llm` *target* adapter accepts `provider: ollama` (defaults to the local
  Ollama endpoint) for testing a local model as the system under test.

### Changed
- Mock-vs-live detection is now provider-aware: a local provider (Ollama) runs
  live with no key; key-providers (Anthropic/OpenAI) fall back to mock only when
  the key is absent. Default behavior (Anthropic) is unchanged.

## [0.4.0] - 2026-06-11

### Added
- **Control-plane dashboard** — launch runs from the UI (pick a config + dials +
  persona panel, watch live progress), not just browse them.
- **Persona studio** — create, generate, edit, and select persona panels in the dashboard.
- **Persona summary in reports** — the persona panel (summaries, verdicts, radar,
  rubric-vs-persona divergences) now appears in the HTML, Markdown, and docx reports.
- **Case-level A/B diff + case explorer** — same-prompt responses side by side across
  two runs with score deltas, and a searchable/sortable/filterable case table.

## [0.3.0] - 2026-06-11

### Added
- **Scoring depth** — weighted assertions, per-test thresholds, `negate`, and metric
  tagging; new assertion kinds (`icontains`, `contains_any`/`contains_all`,
  `starts_with`, `is_refusal`, `levenshtein`, `cost_under`, `similar` [semantic
  similarity with a pluggable embedder + offline mock], `python`/`callable`
  [AST-sandboxed custom code, disabled by default]); **named + derived (F1-style)
  metrics**; a weighted gate mode; `cost_usd` now populated by the llm/http/demo adapters.
- **History, comparison & trend** — run lineage (corpus/rubric/config fingerprints,
  SUT git sha/ref, project); comparability-gated **N-run comparison**, per-dimension
  **trends with slope**, **regression detection**, and a rolling-window baseline; new
  `compare --runs`, `trend`, and `regressions` CLI commands.
- **Forensic v2** — every leverage change carries a concrete **`suggested_fix`**
  (file / locus / rationale / diff), grounded in real source when a checkout is provided.
- **Visuals** — dashboard score heatmap, compare matrix, per-dimension trend lines,
  persona radar, and a root-cause → suggested-fix view (all inline SVG, offline);
  presentation-grade HTML reports with inline-SVG charts.
- **Local dashboard** (`polygraph dashboard`), **Jinja2 report templates + branding**,
  and **prompt-corpus export** (`polygraph export` → json/jsonl/csv).

### Changed
- All additions are backward compatible; the strict gate reproduces prior verdicts exactly.

## [0.1.1] - 2026-06-09

Initial public release.

### Added
- Synthetic corpora (fixed / varied / adversarial / hybrid) with an LLM generator.
- Adapters: HTTP/REST, LLM chat (OpenAI-compatible / Anthropic), in-process callable, demo.
- Async runner: concurrency, retry, resume, response cache.
- Deterministic assertions + an LLM rubric scorer with a multi-judge ensemble; a
  cumulative pass/fail gate and baseline diff.
- **Persona reaction panel** reconciled against the rubric, and a **forensic audit**
  that reads a local source tree to cite `file:line` root causes.
- **SME golden-probe elicitation** (`polygraph elicit`) and **domain scaffolding**
  (`polygraph tune`).
- Reports in markdown / docx / pdf / html; A/B compare + baselines.
- Example packs: everyday-assistant (default), support-bot, clinical-trials.
- Deployable service: FastAPI API + worker + Postgres job queue + scheduler + webhooks
  + dashboard; one Docker image, AWS/GCP deploy guides; CI workflow.

[Unreleased]: https://github.com/justinkastil/promptpolygraph/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.4.0
[0.3.0]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.3.0
[0.1.1]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.1.1
