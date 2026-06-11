# Architecture

PromptPolygraph is a local-first, cloud-agnostic harness for evaluating and
red-teaming web/API/LLM systems at scale. It is a pure Python library with a CLI
and two optional deployment shells (a local dashboard and a multi-user service)
that wrap the **same** engine without modifying it.

This document describes the runtime components, data flow, extension points, and
deployment topologies. It is also the reference for the validation work tracked
toward the 1.0 release (see the v1.0 epic) — institutions adopting the tool need
to understand exactly what runs, what it depends on, and where adversarial
content lives.

---

## 1. Design principles

- **Local-first, no mandatory infrastructure.** A bare `Config()` runs in one
  process against the built-in demo target with no API key, no database server,
  and no work queue. Concurrency (an asyncio pool), not a job queue, drives
  thousands of prompts; SQLite gives durable checkpoint/resume.
- **Adapter-per-target.** The only integration point with the system under test
  is `Adapter.query(case) -> Response`. Everything else is target-agnostic.
- **Data, not code, drives evaluation.** Rubrics, dimensions, thresholds,
  assertions, personas, and attacker profiles are declarative config.
- **Interfaces at the seams.** The store and dispatch sit behind protocols, so
  the service/worker deployment is additive — no engine rewrite.
- **Offline determinism.** A `mock` mode produces deterministic outputs across
  the whole engine (corpus, scoring, audit, red-team) so demos and CI need no
  network and no tokens.
- **Pluggable backends.** The grader/judge/audit/generation backend is any
  Anthropic or OpenAI-compatible endpoint (incl. local Ollama/vLLM/LM Studio),
  independent of the target.

---

## 2. Component map

```
                         ┌──────────────────────────────────────────────┐
   CLI (polygraph)       │                  ENGINE (library)             │
   Dashboard (SSE)  ───► │                                              │
   Service (WS/REST) ──► │   Config  ─►  Corpus  ─►  Runner  ─►  Adapter │ ─► target
                         │                              │               │     system
                         │            Store (SQLite/SQL)│  Response ◄────┘
                         │                              ▼                │
                         │     Analyze (assertions + LLM ensemble) ─► Gate
                         │                              ▼                │
                         │     Audit (persona panel + forensic)         │
                         │                              ▼                │
                         │     Report (md / html / docx / pdf / json)   │
                         └──────────────────────────────────────────────┘

                         ┌──────────────────────────────────────────────┐
                         │              RED-TEAM ENGINE                   │
   Arena (SSE / WS) ◄────│  Profile (attacker roster)                    │
                         │    ├─ LLM attackers ⨯ multi-turn modes        │
                         │    │    (escalate · PAIR · Crescendo · TAP)    │
                         │    │    ⨯ converters (base64/rot13/many-shot…) │
                         │    └─ OSS sources (catalog · garak · PyRIT ·   │
                         │         DeepTeam · datasets) ── extra_sources  │
                         │            │                                  │
                         │            ▼  Adapter ─► target                │
                         │     Breach judge (LLM reviewer | Llama-Guard)  │
                         │            ▼                                  │
                         │     Vulnerability report (ASR + OWASP/ATLAS)   │
                         │     + live event stream  ──────────────────────┘
                         └──────────────────────────────────────────────┘
```

### Evaluation pipeline (`src/promptpolygraph/`)
- **`config.py`** — one `Config` wiring adapter, corpus, runner, analyzer,
  audit, report, red-team, and LLM-backend settings; every field defaulted.
- **`corpus/`** — load fixed probe sets (with a content fingerprint for
  run-over-run identity) or generate varied/adversarial corpora.
- **`adapters/`** — `Adapter` protocol + HTTP, LLM-chat, callable, and demo
  reference adapters. The per-system integration point.
- **`runner/`** — asyncio fan-out with concurrency cap, rate limit, per-case
  timeout, retry, and resume; `store.py` (SQLite + JSONL export + response/score
  cache) and a SQL store behind the same protocol.
- **`analyze/`** — deterministic assertion scorers, an LLM rubric scorer with a
  multi-judge ensemble, derived metrics, and a cumulative gate.
- **`audit/`** — a persona reaction panel reconciled against the rubric, and a
  forensic agent that traces failures to `file:line` + a suggested fix.
- **`report/`** — Markdown / HTML / docx / pdf / JSON renderers with templates
  and branding.

### Red-team engine (`src/promptpolygraph/redteam/`)
- **`models.py`** — `Attacker`, `BreachVerdict`, `AttackAttempt`,
  `Vulnerability` (with OWASP/ATLAS), `RedTeamProfile`, `RedTeamReport`, and the
  `RedTeamEvent` live-stream protocol.
- **`profiles.py`** — preconfigured teams (`all_frontier` default, `deep`,
  `mixed`, `local_swarm`, `pressure`, `multi_frontier`, `quick`).
- **`strategies.py`** — strategy families and probe crafting (seeded + mutated
  from the catalog, not blank-slate).
- **`catalog.py`** — known techniques mapped to the OWASP Top-10 for LLM Apps and
  MITRE ATLAS; the grounding + standards source of truth.
- **`multiturn.py`** — PAIR, Crescendo, and TAP advanced multi-turn strategies.
- **`converters.py`** — probe transforms + many-shot.
- **`sources/`** — the `AttackSource` interface + registry; built-in `catalog`
  source and optional garak / PyRIT / DeepTeam / dataset sources.
- **`judge.py` / `guard.py`** — the LLM-reviewer breach judge and the
  Llama-Guard-style safety-classifier judge.
- **`orchestrator.py`** — runs the roster + external sources through the target
  and judge, aggregates vulnerabilities, computes ASR + OWASP coverage, and emits
  the live event stream.

---

## 3. Data flow

### Evaluation run
`Corpus → Runner (async pool) → Adapter → target → Response → Store + cache →
Analyze (assertions, then LLM ensemble) → Gate → Audit (persona + forensic) →
Report`. Resume reads completed cases from the store; the cache makes
re-analyze / re-audit free of re-querying the target.

### Red-team run
`Profile → for each attacker: craft/refine probe (per mode) → optional converter
→ Adapter → target → Response → Breach judge → AttackAttempt`, in parallel under
a semaphore. External `extra_sources` emit probes through the same target→judge
path, attributed to the source. Breached attempts aggregate into severity-ranked
`Vulnerability` records carrying OWASP/ATLAS; `stats` carries ASR + OWASP
coverage. Every step emits a `RedTeamEvent` that the CLI logs and the
dashboard/service render as the Arena.

---

## 4. Extension points

| Extend… | Implement / register | Where |
|---|---|---|
| A new target system | `Adapter.query(case) -> Response` | `adapters/` |
| A new evaluation signal | an assertion scorer | `analyze/assertions.py` |
| A new scoring backend | OpenAI-compatible endpoint via config | `llm.py` |
| A new attacker team | a `RedTeamProfile` | `redteam/profiles.py` |
| A new attack technique | a `Technique` in the catalog | `redteam/catalog.py` |
| A new probe source | `AttackSource` + `register_source` | `redteam/sources/` |
| A new breach judge | an async `(client, attempt, *, …) -> BreachVerdict` | `redteam/` |
| A new report format | a renderer | `report/` |

External attack sources register only when their optional dependency imports, so
a bare install is never broken by a missing extra.

---

## 5. Deployment topologies

1. **Laptop / CI runner** — `pip install`, run the CLI. SQLite store, in-process
   concurrency. Mock mode needs no network.
2. **Container** — one image; PDF rendering optional via LibreOffice build arg.
3. **Service mode** — a FastAPI app + worker(s) sharing a SQL (Postgres) store
   and a job queue (`SELECT … FOR UPDATE SKIP LOCKED`), fanning runs across
   workers. Cloud-agnostic (AWS App Runner/ECS/EKS or GCP Cloud Run). The Arena
   streams over WebSocket; evaluation runs stream progress over the same channel.

---

## 6. Trust & validation surface (1.0 focus)

For an institution to trust the data PromptPolygraph reports, these properties
are being formalized for the 1.0 release (tracked in the v1.0 validation epic):

- **Provenance** — every probe/source/dataset carries origin, license, version,
  and checksum; a per-run provenance manifest records exactly what was used.
- **Reference integrity** — OWASP/ATLAS/technique mappings cite pinned source
  versions; CI fails on an unsourced mapping.
- **Reproducibility** — seeded, fingerprinted runs; documented bounds on
  LLM-sampling nondeterminism; byte-stable mock mode; re-run diffing.
- **Judge calibration** — breach-judge and rubric scorers validated against
  labeled ground truth with inter-rater agreement and error rates published.
- **Statistical rigor** — ASR with confidence intervals; significance testing on
  run-over-run regressions; sample-size guidance.
- **Integrity of record** — versioned report schema, immutable run records, and
  optional signed/verifiable report artifacts with a tamper-evident audit log.

See `docs/REDTEAM_LOCAL.md` for running attacker/judge models locally.
