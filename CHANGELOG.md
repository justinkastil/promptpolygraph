# Changelog

All notable changes to PromptPolygraph are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Integrity of record** (toward 1.0). Public-key signing for run bundles:
  `signing.py` adds Ed25519 (optional `[crypto]` extra) alongside the existing
  HMAC; `polygraph keygen` writes a keypair, `polygraph bundle --sign-key`
  signs, and `polygraph verify --pub-key` verifies (HMAC stays the no-dep
  default; legacy HMAC bundles still verify). Versioned run records: `RunMeta`
  gains `schema_version` and `migrations.py` upgrades older records forward on
  read (the store migrates transparently). Tamper-evident `audit_log.py`: an
  append-only, hash-chained log of privileged actions with `verify_chain`
  pinpointing any break; `polygraph audit-log verify` gates on it. `polygraph
  validate` now exercises signing, schema versioning, and the audit-log chain.
- **Service-mode hardening — multi-tenant RBAC** (toward 1.0). `service/tenancy.py`
  adds **workspaces** as the isolation boundary, **RBAC** (admin > editor >
  viewer), and **per-workspace API keys hashed at rest** (shown once on
  creation). Runs are stamped to a workspace and a request only sees its own
  workspace's runs — cross-workspace reads return **404** (existence is not
  leaked). New admin endpoints: `/api/workspaces`, `/api/members`, `/api/keys`
  (create/list/revoke), `/api/audit-log` (a per-workspace hash-chained log of
  privileged actions + chain verification), and `/api/whoami`. Backward
  compatible: a legacy flat `POLYGRAPH_API_KEYS` value resolves to admin of the
  `default` workspace, and an auth-disabled dev server to the same — existing
  deployments are unchanged.
- **Service-mode hardening — OIDC/SSO** (toward 1.0; `service/oidc.py`, optional
  `[oidc]` extra). Human login via an IdP (Okta/Entra/Keycloak/Auth0): a bearer
  JWT is verified against the IdP's JWKS (issuer/audience/expiry checked, MFA
  optionally required via the `amr`/`acr` claim) and the token's identity is
  mapped to a workspace member's role. **Fully optional and off by default** —
  inert unless `oidc_issuer` is set; per-workspace API keys remain the CI /
  service-account credential and the existing auth paths are unchanged.
- **Statistical depth — power, sample-size & variance** (toward 1.0). New
  `analyze/stats.py` functions: `sample_size_for_proportion` (probes to estimate
  a rate to ±margin), `min_n_for_proportion_diff` (MDE / per-run n to detect a
  rate change at a target power), `power_for_proportion_diff` (achieved power),
  and `variance_components` (one-way ICC decomposing score variance into real
  between-case signal vs judge noise). A `polygraph power` command does
  sample-size / power planning; the eval summary's `confidence` block gains a
  per-dimension `reliability` (ICC) section when an ensemble graded each case.
- **Governance & responsible use** (toward 1.0). New `RESPONSIBLE_USE.md`
  (authorized-use boundaries), `CONTRIBUTING.md`, and `GOVERNANCE.md`.
  Adversarial datasets are now **opt-in**: the live fetch of a harmful-behaviour
  dataset (`dataset:advbench` / `harmbench` / `jailbreakbench`) is gated behind
  `POLYGRAPH_ACCEPT_DATASET_TERMS=1` — without it the source stays on benign
  placeholder probes (and warns), so a default run never pulls harmful content
  silently.

## [0.7.0] - 2026-06-19

A CI/CD-integration release plus the first of the 1.0 validation/trust spine.

### Added
- **Validation package** (`validate.py`, `polygraph validate`): a regenerable
  IQ/OQ/PQ evidence bundle. IQ qualifies the install (Python, dependencies,
  packaged data, reference integrity); OQ exercises each component on golden
  inputs (stats, corpus+gate, report renderers incl. valid JUnit/SARIF,
  red-team ASR+CI, calibration); PQ confirms a mock run reproduces byte-for-byte.
  Writes `evidence.json` + `evidence.md`, exits non-zero on any failure, runs in
  CI. New `docs/VALIDATION.md`.
- **Statistical rigor** (`analyze/stats.py`): Wilson-score confidence intervals
  on proportions (the red-team **ASR now ships with a 95% CI**; assertion pass
  rate too), a seeded/deterministic percentile bootstrap on continuous
  aggregates (per-category dimension means), Student-t mean intervals, two-
  proportion and Welch tests, exact McNemar, and Benjamini-Hochberg FDR. The
  eval summary gains a `confidence` block (per-(category,dimension) CIs + a
  small-sample warning) and a `gate_band` verdict. New `analyze.respect_ci`
  makes the gate return *inconclusive* — not fail — when the threshold falls
  inside a metric's CI band (default off; the strict point gate is unchanged).
- **Significance testing for regressions**: `diff_baseline` reports a
  statistical verdict (two-sample test on each per-dimension delta, BH-corrected
  across dimensions) alongside the heuristic dead-band, so a multi-dimension
  sweep does not manufacture false regressions. New `significant_regressions` /
  `significant_improvements` with q-values; gracefully unavailable against a
  baseline that predates the CI layer.
- **Machine-readable CI output**: JUnit XML and SARIF 2.1.0 renderers for both
  eval and red-team runs (`--format junit,sarif`). SARIF findings render inline
  on a PR via GitHub/GitLab code scanning; a code-grounded red-team trace
  attaches a `file:line` location.
- **One-step regression gate + PR feedback**: `analyze --ci` gains `--baseline`
  (run id / `rolling:N` / `HEAD`), `--github-annotations` (emit
  `::error`/`::warning` + a `$GITHUB_STEP_SUMMARY` job summary), and
  `--pr-comment PATH` (a markdown summary with the per-category table, the
  assertion-pass-rate CI, and baseline movement).
- **Config validation + schemas**: `polygraph validate-config` fails fast on a
  malformed config/rubric with a precise dotted path per error (and warns on
  unknown keys the tolerant loader would ignore); `polygraph schema` writes
  config + rubric JSON Schemas for editor autocomplete.
- **CI scaffolding**: `polygraph scaffold-ci {github,gitlab,jenkins,precommit}`
  writes a working starter pipeline (validate → gate → JUnit/SARIF → PR
  feedback → red-team). New `docs/CI.md`.
- **Rubric-vs-persona discordance scatter** in the HTML report: per-case rubric
  score vs persona-perceived value with threshold quadrants; the lower-right
  quadrant (high score, low trust) is highlighted as the actionable off-diagonal.
- **Provenance + reference integrity** (`provenance.py`): a per-run provenance
  manifest (tool/version/deps, fingerprints, and — for red-team — probe sources
  with their package versions and the pinned standards mapping); auto-written
  beside red-team runs and via `polygraph manifest --run <id>`. The
  technique→OWASP/ATLAS mapping is pinned behind a checksummed lock
  (`data/references.lock.json`); `polygraph references --check` (run in CI)
  fails on drift or any unmapped technique. The wheel now ships the lock.
- **Judge calibration** (`calibrate.py`, `polygraph calibrate`): scores the
  breach judge against a bundled, human-labeled ground-truth set
  (`data/ground_truth_breaches.json`) and reports precision/recall/F1/accuracy,
  the confusion matrix, and Cohen's κ on the breach decision + severity, with a
  reliability verdict and the disagreement list. `--min-f1` gates CI on judge
  reliability; `--guard` calibrates the Llama-Guard judge. New κ /
  classification primitives in `analyze/stats.py` (`cohen_kappa`,
  `fleiss_kappa`, `binary_classification_metrics`).
- **Sealed run bundles** (`reproducibility.py`, `polygraph bundle` /
  `polygraph verify`): pack a run's artifacts into a `.tar.gz` with a SHA-256
  manifest of every file plus tool/dependency provenance; `verify` re-hashes the
  contents and refuses (non-zero) on any tampered/missing/extra file. An
  optional HMAC signature (`POLYGRAPH_SIGNING_KEY`) adds origin authentication
  (stdlib only, no crypto dependency). `unbundle` re-inflates for offline replay.
- **Trust docs**: `docs/THREAT_MODEL.md` (trust boundaries, assets, risks +
  controls: adversarial content, code-dive egress, the assertion sandbox,
  integrity/signing, reference drift, supply chain) and `SECURITY.md`
  (disclosure + safe use).

### Changed
- `__version__` now reads from the installed package metadata (was hardcoded).

## [0.6.7] - 2026-06-15

### Fixed
- LLM judging against the default model: `AnthropicClient` sent `temperature`
  to `claude-opus-4-8` (the default judge/audit/generation model), which the
  model rejects with HTTP 400. Every analyzer and audit call failed and fell
  back to `n/a` scores, so a default `polygraph all` run with real judging
  produced no rubric scores. The client now omits sampling params
  (`temperature`/`top_p`/`top_k`) for models that reject them — Opus 4.8/4.7
  and Fable 5/Mythos 5 — and keeps sending `temperature` to models that still
  accept it (Opus 4.6, Sonnet 4.6, Haiku 4.5). `OpenAICompatibleClient` is
  unaffected.
- `__version__` was stale at `0.1.0`; now tracks the release version.

## [0.6.6] - 2026-06-13

### Fixed
- Package version metadata: `pyproject.toml` now reports the project's actual
  version (was stale at `0.1.0`). First release published to PyPI.

## [0.6.5] - 2026-06-11

### Added
- Generation progress: corpus generation streams steps (plan/batch/prompt) — a
  live progress bar + prompt list in the Studio, a live counter in the CLI.
- Provider discovery + `polygraph init`: detects usable backends (API key present
  / Ollama reachable) and their models; `GET /api/providers` + `GET /api/status`
  drive provider/model dropdowns and a header status pill (Live vs Mock-only).
- Config builder (New run): compose a config (identity, a type-aware target
  adapter, corpus + custom-category editor, analysis/audit/report, red-team,
  backend), save (`POST /api/configs`) / load (`GET /api/config`) / launch.
- AI Designer: a collapsible dock that designs a run config (`POST /api/config/design`)
  or a red-team config (`POST /api/redteam/design`, grounded in the technique
  catalog + installed sources + profiles) and injects it; a designed red-team
  roster runs as a custom profile (`POST /api/redteam/profile` → `?profile_ref=`).
- Target connection: a "Test connection" button + `POST /api/adapter/test`; a
  callable adapter is configurable by `module:function` import string.
- Tooltips across the config/Studio/Arena controls.

### Changed
- Unified the Arena and dashboard chrome (shared header/theme via `ui/chrome.py`).
- Corpus generation defaults to 8 prompts/category when count + per-category are
  blank (was zero); the UI states the amount.
- The rendered-page term check reads its list from the environment rather than
  hardcoding any terms in the source.

## [0.6.0] - 2026-06-11

### Added
- Arena drill-down: click an attacker for the per-turn timeline (probe/response/
  verdict per turn) and the root cause.
- Code-grounded root-cause ladder (opt-in via `redteam.code_path`): a model pass
  over a local checkout cites `file:line` rungs of the target source, colored by
  stage state (broken/weak/held), with a suggested-fix diff; source windows are
  re-read from disk. With no `code_path` it returns a finding summary (control,
  OWASP/ATLAS, mitigation) instead of a ladder.
- Code-dive egress controls: defaults to a local model; a non-local provider is
  refused when `POLYGRAPH_AIR_GAP=1` and otherwise requires `consent` in the
  request. Excerpts are secret-scrubbed before send; indexing honors
  `.gitignore` / `.polygraphignore` in addition to the vendor-dir skip.
- Replay: Arena runs are persisted to `out_dir/redteam/<id>/`; Live/Replay
  toggle. Endpoints: `GET /api/redteam/runs`, `/api/redteam/runs/{id}`,
  `/api/redteam/runs/{id}/events`; `POST /api/redteam/trace`.
- Arena lanes show technique/source, provider, and mode; scoreboard shows ASR +
  an OWASP coverage grid; a findings table. OSS source quick-add chips and a
  Trace-in-code `code_path` field.
- Studio (renamed from Personas, with Prompts | Personas sub-tabs): prompt-corpus
  generator — `POST /api/corpus/generate` (mode/domain/difficulty/count/
  per_category/categories/seed; pluggable provider+model; mock), preview, export
  via `GET /api/corpus/export` (json/jsonl/csv, path-guarded), and "use in new
  run" (corpus path override on `/api/run`).

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

[Unreleased]: https://github.com/justinkastil/promptpolygraph/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/justinkastil/promptpolygraph/compare/v0.6.7...v0.7.0
[0.6.6]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.6.6
[0.6.5]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.6.5
[0.6.0]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.6.0
[0.5.1]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.5.1
[0.5.0]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.5.0
[0.4.1]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.4.1
[0.4.0]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.4.0
[0.3.0]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.3.0
[0.1.1]: https://github.com/justinkastil/promptpolygraph/releases/tag/v0.1.1
