# PromptPolygraph

**Synthetic-prompt evaluation and persona-audit harness for web and API AI systems.**

PromptPolygraph pushes thousands of synthetic prompts through any web/API/LLM system, scores the
responses against a pluggable rubric (plus cheap deterministic assertions and an optional multi-judge
ensemble), reacts to them through a panel of personas, traces low scores with a forensic audit, and
renders the result as a markdown / docx / pdf / html report.

It is **local-first and cloud-agnostic**: one process, an async concurrency pool, and a SQLite store —
runs on a laptop, a CI runner, or a container. No work queue, no database server, nothing to deploy. It also
ships a **deployable API + worker** (Postgres-backed, Dockerized) for multi-user, team-scale use — see
[Service mode](#service-mode-multi-user-scalable).

> Status: the local harness (CLI) and the service layer are both built and tested. Runs fully offline in
> `--mock` mode; the Docker image and the `postgres + api + worker` compose stack are verified end to end.

## Why

Evaluating an AI system well means more than a single accuracy number. PromptPolygraph combines:

- **Synthetic corpora** — a fixed deterministic set for clean run-over-run baselining, or LLM-generated
  *varied* / *adversarial* probes, with dials for quantity, categories, difficulty, and seed.
- **Adapters** — one small class (`async def query(case) -> Response`) per system under test. Ships an
  HTTP/REST adapter, an LLM-chat adapter, and an in-process callable adapter.
- **Layered scoring** — deterministic assertions (contains / regex / json-schema / latency) run first;
  then an LLM rubric scorer with an optional multi-judge ensemble and inter-judge agreement.
- **Persona panel** — a pool of distinct individuals react to the real responses (trust, usefulness,
  clarity, would-return), reconciled against the rubric so you optimize real value, not just the number.
- **Forensic audit** — per-category agents trace low scores to failure modes and the highest-leverage fixes.
- **Reports** — a polished review document in markdown, docx, pdf, and html.

## Install

```bash
pip install -e ".[dev]"        # core + test deps
pip install -e ".[dev,llm]"    # + OpenAI-compatible adapter
```

Requires Python 3.10+.

## Quickstart

```bash
# Offline end-to-end demo against the bundled example (no API key needed):
# runs a fixed corpus through a built-in demo target, scores it, runs the persona
# + forensic audit, and writes md/html/docx/pdf reports under polygraph_out/.
polygraph all --config examples/everyday_assistant/config.yaml --mock --format md,html,docx,pdf
```

With an `ANTHROPIC_API_KEY` set and a real adapter configured, drop `--mock`.

**Bundled example packs** (each a self-contained `config + corpus + rubric + personas`):
- `examples/everyday_assistant/` — the default: a neutral general-purpose assistant (general knowledge, how-tos, reasoning, refusal, safety, edge input).
- `examples/support_bot/` — a customer-support assistant for a fictional SaaS.
- `examples/clinical_trials/` — a domain pack for a clinical-trial-protocol assistant (personas for medical writer, clinical scientist, data manager, medical director, regulatory, biostatistician, clinical ops, pharmacovigilance).

Copy one as a starting point, or generate a fresh tailored pack with `polygraph tune` (see below).

## Runbook

### 1. Point an adapter at your system
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
For anything exotic, implement `async def query(self, case) -> Response` and pass an in-process
callable with `--callable mymodule:my_fn`.

### 2. Choose a corpus mode (dials)
```bash
polygraph run --config c.yaml --mode fixed                       # deterministic set; stable ids for baselining
polygraph run --config c.yaml --mode varied      --count 1000    # fresh LLM-generated each run
polygraph run --config c.yaml --mode adversarial --count 500 --difficulty aggressive
polygraph run --config c.yaml --mode hybrid       --count 800    # fixed core + generated supplement
```
Dials: `--count`, `--per-category`, `--categories a,b,c`, `--difficulty {mild|standard|aggressive}`,
`--concurrency`, plus `rps`/`timeout`/`retries`/`resume` in the config. Thousands of prompts is just the
concurrency pool; runs are durable and `--resume`-able.

### 3. Score
```bash
polygraph analyze --config c.yaml --run <run_id> --judges 3 --ci
```
Deterministic assertions (declared per probe: contains / regex / json-schema / latency …) run first; then
an LLM rubric scorer. `--judges N` adds an ensemble with inter-judge agreement. `--ci` exits non-zero if the
gate fails (per-dimension threshold, cumulative across categories). The rubric is a YAML pack — edit
`rubric.yaml` (dimensions, anchors, per-category applicability, threshold) for your domain.

### 4. Audit (persona panel + forensic)
```bash
polygraph audit --config c.yaml --run <run_id>
```
A panel of personas reacts to the real responses (trust / usefulness / clarity / would-return) and is
reconciled against the rubric so you optimize real value, not just the number; per-category forensic agents
trace low scores to the highest-leverage fixes.

Manage personas:
```bash
polygraph personas list
polygraph personas new "a grumpy retiree who hates phone trees" --out persona.yaml
polygraph personas generate --domain "developer tools" --count 8 --out panel.yaml
```
Select a panel via `personas_path:` (a YAML file), `audit.persona_pool: N` (sample the 13-persona library),
or `audit.personas: [ids]`.

### 5. Report & compare
```bash
polygraph report  --config c.yaml --run <run_id> --format md,docx,pdf,html --baseline <prior_run_id>
polygraph compare --config c.yaml --run-a <run_id> --run-b <other_run_id>     # A/B win/loss/tie
```
`--baseline` adds Δ-vs-prior columns + regression flags. `compare` runs the same corpus through two systems
(or model versions) and tallies per-case win/loss/tie. PDF uses LibreOffice headless when available and is
skipped gracefully otherwise.

### One-shot
```bash
polygraph all --config c.yaml --format md,html        # run -> analyze -> audit -> report
```

### Tailor it to your domain
Set a `domain` (a one-line description of the system under test) and the generated **prompts** — and,
with `audit.tailor_personas`, the **persona panel** — are specific to it instead of generic:

```bash
polygraph all --config c.yaml --mode adversarial --count 500 \
  --domain "Clinical trial protocol digitalization assistant"
```

Or scaffold a whole tailored project (rubric + persona panel + starter corpus + config) for a domain in one
command, then refine the files and point the adapter at your system:

```bash
polygraph tune --domain "Clinical trial protocol digitalization assistant" --out projects/ctpd
polygraph all  --config projects/ctpd/config.yaml --mock
```

### Bootstrap a golden set with a subject-matter expert
`polygraph tune` auto-scaffolds; **`polygraph elicit`** builds an *expert-validated* golden corpus through
a guided, human-in-the-loop walkthrough:

```bash
polygraph elicit interview --domain "Clinical trial protocol digitalization assistant" --out brief.yaml
#   (or: polygraph elicit init --domain "..." --out brief.yaml   — fill the brief by hand/async)
polygraph elicit build    --brief brief.yaml --out projects/ctpd     # draft probes + review sheet + rubric + personas
#   the SME edits projects/ctpd/review.yaml (set `decision: reject` to drop a probe, or edit any field)
polygraph elicit finalize --review projects/ctpd/review.yaml --out projects/ctpd   # accepted probes -> golden corpus
polygraph all --config projects/ctpd/config.yaml --mock
```

The interview asks the expert what the system does, what good/bad answers look like per category, the failure
modes and must-refuse cases, and real example queries; probes are drafted **grounded in those answers**, then
gated by the expert's review — which is what makes the set *golden*. Personas are drawn from the expert roles
named in the brief.

A ready-made **clinical-trials** pack ships under `examples/clinical_trials/` (personas for medical writer,
clinical scientist, data manager, medical director, regulatory, biostatistician, clinical ops, and
pharmacovigilance; a protocol-focused corpus and rubric):

```bash
polygraph all --config examples/clinical_trials/config.yaml --mock --format md,html
```

## Architecture

One local process: `Corpus → Runner (async pool, timeout/retry/resume) → Adapter → target → Response →
SQLite + cache → Analyze (assertions + LLM ensemble) → Gate → Audit (persona + forensic) → Report`. No work
queue, no database server. The store and dispatch sit behind interfaces, so a service/worker deployment can
wrap the same engine without touching it.

## Service mode (multi-user, scalable)

The same engine runs as a deployable API + worker for a team:

```bash
pip install -e ".[service]"
polygraph-server      # FastAPI: trigger runs, poll status, fetch reports, compare, manage personas
polygraph-worker      # claims queued jobs and executes the pipeline (scale horizontally)
# or one container that does both (in-process worker) for local use
```

Or the whole stack in containers (Postgres + API + a separate worker):

```bash
docker compose up --build           # api on :8080, worker scales with --scale worker=N
curl -XPOST localhost:8080/api/runs -H 'X-API-Key: change-me-dev-key' \
     -H 'Content-Type: application/json' -d '{"config_name":"support_bot"}'
```

The default Docker image **includes LibreOffice**, so PDF reports render in-container; build with
`--build-arg INCLUDE_PDF=false` for a slimmer image (html/md/docx still work).

- **Store**: SQLite locally, Postgres in production (same code, just `POLYGRAPH_DATABASE_URL`). A durable job
  queue lets many workers pull work safely (`FOR UPDATE SKIP LOCKED` on Postgres).
- **API** (`/api`, API-key auth): create runs, poll status + live progress, fetch summary/report
  (html & markdown re-render from the DB), browse cases, A/B compare, manage personas. Plus a dashboard at `/`.
- **Scheduling & CI**: cron schedules enqueue recurring runs; per-run or global webhooks POST a summary on
  completion; `--ci`-style gating is available via the run verdict.
- **Deploy**: one Docker image, two roles, on **AWS** (App Runner / ECS Fargate / EKS) or **GCP** (Cloud Run).

See [docs/SERVICE.md](docs/SERVICE.md) for the operator runbook and [deploy/README.md](deploy/README.md) for
cloud deployment.

## Development

```bash
pip install -e ".[dev,service]"
pytest -q                                   # full suite
python -m promptpolygraph --help            # same as the `polygraph` CLI
python -m build                             # build wheel + sdist
```

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.11/3.12, smoke-tests the
default example offline, and verifies the built wheel ships the persona data.

## License

Apache-2.0. See [LICENSE](LICENSE).
