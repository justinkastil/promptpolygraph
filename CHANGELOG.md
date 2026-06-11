# Changelog

All notable changes to PromptPolygraph are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/justinkastil/promptpolygraph/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.3.0
[0.1.1]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.1.1
