# PromptPolygraph Service — Operator Runbook

The service wraps the evaluation engine behind an HTTP API and a durable job
queue. It is **one image, two roles**:

- **API** (`polygraph-server`) — accepts run requests, persists them as queued
  jobs, and serves status, summaries, reports, comparisons, and personas. Also
  hosts a dashboard at `/`.
- **Worker** (`polygraph-worker`) — claims queued jobs and runs the pipeline
  (corpus → target → analyze → audit → report).

Storage is a single SQLAlchemy URL: **sqlite** for local/dev, **Postgres** for
production. The worker claim protocol uses `FOR UPDATE SKIP LOCKED` on Postgres
so any number of workers pull distinct jobs safely.

For a single-container or local setup the API can run the worker **in-process**
(`POLYGRAPH_INPROCESS_WORKER=true`), so one process does both jobs.

---

## Run locally

```bash
pip install -e ".[service]"
```

Set configuration via `POLYGRAPH_*` environment variables (or a `.env` file):

| Variable                     | Default                              | Purpose |
|------------------------------|--------------------------------------|---------|
| `POLYGRAPH_DATABASE_URL`     | `sqlite:///polygraph_service.sqlite` | Store + job queue. `postgresql+psycopg://user:pw@host/db` in prod. |
| `POLYGRAPH_API_KEYS`         | *(empty)*                            | Comma-separated keys. Empty disables auth (dev only). |
| `POLYGRAPH_OUT_DIR`          | `polygraph_out`                      | Where each run writes `summary.json`, `audit.json`, and report artifacts. |
| `POLYGRAPH_CONFIG_DIR`       | `configs`                            | Directory of `<name>.yaml` configs the API can launch by `config_name`. |
| `POLYGRAPH_INPROCESS_WORKER` | `true`                               | API also runs a worker thread. Set `false` in prod (dedicated workers). |
| `POLYGRAPH_SCHEDULES_PATH`   | *(unset)*                            | Path to a `schedules.yaml`; when set, the API starts a cron scheduler. |
| `POLYGRAPH_WEBHOOK_URL`      | *(unset)*                            | Global completion webhook (per-run `webhook_url` overrides it). |
| `POLYGRAPH_DEFAULT_MOCK`     | `false`                              | Default to offline/mock execution when a request omits `mock`. |
| `ANTHROPIC_API_KEY`          | *(unset)*                            | Credential for live (non-mock) target/judge calls. |

Other useful dials: `POLYGRAPH_WORKER_POLL_S` (idle poll interval),
`POLYGRAPH_WORKER_CONCURRENCY`, `POLYGRAPH_HOST` / `POLYGRAPH_PORT`.

Start the two roles (separate terminals for local dev, or one with the
in-process worker):

```bash
polygraph-server     # API + dashboard on :8080
polygraph-worker     # one or more worker processes (optional if INPROCESS_WORKER=true)
```

### curl examples

All `/api/*` endpoints require `X-API-Key` when keys are configured.

```bash
KEY=test-key
BASE=http://localhost:8080

# 1. Create a run (named config from CONFIG_DIR, offline, 2 cases/category, two report formats)
curl -s -X POST $BASE/api/runs \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"config_name":"config","mock":true,"overrides":{"per_category":2},"formats":["md","html"]}'
# -> {"run_id":"...","job_id":"...","status":"queued"}

RUN=<run_id from above>

# 2. Poll status until done
curl -s $BASE/api/runs/$RUN -H "X-API-Key: $KEY"
# -> {"run_id":"...","status":"queued|running|done|failed","progress":{...},...}

# 3. Fetch the summary + the HTML report
curl -s $BASE/api/runs/$RUN/summary -H "X-API-Key: $KEY"
curl -s "$BASE/api/runs/$RUN/report?format=html" -H "X-API-Key: $KEY" -o report.html

# 4. List jobs
curl -s $BASE/api/jobs -H "X-API-Key: $KEY"

# 5. Compare two runs
curl -s "$BASE/api/compare?run_a=$RUN_A&run_b=$RUN_B" -H "X-API-Key: $KEY"

# 6. List the persona library
curl -s $BASE/api/personas -H "X-API-Key: $KEY"
```

Create-run request fields: provide exactly one of `config` (inline dict),
`config_path` (absolute path), or `config_name` (resolves to
`CONFIG_DIR/<name>.yaml`). Optional: `overrides` (mode, count, per_category,
categories, difficulty, concurrency, judges), `mock`, `priority`, `formats`,
`webhook_url`.

---

## Scaling

- **Run N workers.** Each worker calls `claim_job()`, which atomically selects
  the highest-priority queued job and flips it to `running`. On Postgres this
  uses `FOR UPDATE SKIP LOCKED`, so concurrent workers never claim the same job
  and never block each other — scale workers horizontally to match load.
- **API in prod:** set `POLYGRAPH_INPROCESS_WORKER=false` so the API only
  serves requests, and run workers as separate replicas. (Locally, leave it
  `true` for a single process that does both.)
- Jobs are prioritized: higher `priority` first, then FIFO by creation time.

---

## Scheduling

Point `POLYGRAPH_SCHEDULES_PATH` at a `schedules.yaml`. Each entry is a standard
5-field cron expression that **enqueues** a run on its schedule; the same worker
pool executes scheduled and ad-hoc runs alike.

```yaml
# schedules.yaml
- name: nightly-fixed
  cron: "0 2 * * *"          # min hour dom mon dow
  config_name: config        # or config_path / inline config
  overrides: { mode: fixed }
  mock: false
- name: weekly-adversarial
  cron: "0 3 * * 1"
  config_name: config
  overrides: { mode: adversarial, per_category: 20 }
```

The scheduler runs inside the API process and only fires when
`POLYGRAPH_SCHEDULES_PATH` is set and the file exists.

---

## Webhooks

On run completion (done **or** failed) the service POSTs a compact JSON payload
if a webhook is configured — either per-run (`webhook_url` in the create-run
body) or globally (`POLYGRAPH_WEBHOOK_URL`; the per-run value overrides it).
Delivery is fire-and-forget: a flaky webhook is logged, never fails the run.

Payload shape:

```json
{
  "run_id": "...",
  "job_id": "...",
  "status": "done",
  "overall_pass": true,
  "summary": { ... }
}
```

(On failure: `{"run_id", "job_id", "status": "failed", "error": "..."}`.)

---

## Artifacts: re-rendered vs. served from disk

- **`html`, `md`, and `summary`** re-render on demand from the database when the
  on-disk artifact is absent. They work without a shared volume — the API can
  serve them even if the run executed on a different worker container.
- **`docx` and `pdf`** are served from the run's directory under
  `POLYGRAPH_OUT_DIR` (`OUT_DIR/<run_id>/report.<fmt>`). In a multi-container
  deployment, **mount `OUT_DIR` as a shared volume** so the API can read what a
  worker wrote, or those endpoints return 404. PDF uses LibreOffice for the
  docx→pdf conversion; the default Docker image already includes it (build with
  `--build-arg INCLUDE_PDF=false` for a slimmer image without PDF).

---

## Cloud deployment

See [`deploy/README.md`](https://github.com/justinkastil/promptpolygraph/blob/main/deploy/README.md) for AWS/GCP deployment guidance
(image build, Postgres provisioning, worker/API replica topology, shared volume
for `OUT_DIR`).

## Multi-tenant access control (RBAC)

The service is multi-tenant: **workspaces** are the isolation boundary, and every
run is stamped to the workspace that created it. A request only sees its own
workspace's runs — a cross-workspace read returns `404` (existence is not leaked).

**Roles** are `admin` > `editor` > `viewer`:
- *viewer* — read runs/reports/compare;
- *editor* — also create + cancel runs, create personas;
- *admin* — also manage members + API keys + read the audit log.

**API keys** are minted per workspace and **stored hashed** — the plaintext is
shown once at creation and is not recoverable. Manage them as an admin:

```bash
curl -XPOST $URL/api/keys     -H "X-API-Key: $ADMIN" -d '{"role":"editor","label":"ci"}'   # mint (returns api_key once)
curl       $URL/api/keys      -H "X-API-Key: $ADMIN"                                          # list (metadata only)
curl -XDELETE $URL/api/keys/<prefix> -H "X-API-Key: $ADMIN"                                   # revoke
curl -XPOST $URL/api/workspaces -H "X-API-Key: $ADMIN" -d '{"name":"acme"}'                   # new workspace (+ bootstrap admin key)
curl       $URL/api/whoami    -H "X-API-Key: $KEY"                                            # your workspace + role
curl       $URL/api/audit-log -H "X-API-Key: $ADMIN"                                          # hash-chained log + chain check
```

**Backward compatible:** a legacy flat `POLYGRAPH_API_KEYS` value resolves to an
admin of the `default` workspace, and an auth-disabled dev server to the same —
existing single-tenant deployments are unchanged. OIDC/SSO (human login) is the
next addition; the API-key path covers CI/service accounts today.

## SSO (OIDC/OAuth2) — optional

Human login can be delegated to an IdP (Okta, Entra ID, Keycloak, Auth0). It is
**optional and off by default**: install the `[oidc]` extra and set the issuer to
enable it; per-workspace API keys remain the credential for CI / service accounts.

```bash
pip install 'promptpolygraph[oidc]'
export POLYGRAPH_OIDC_ISSUER=https://your-idp.example.com
export POLYGRAPH_OIDC_AUDIENCE=promptpolygraph        # the token's aud
# export POLYGRAPH_OIDC_JWKS_URL=...                  # optional; derived from the issuer otherwise
# export POLYGRAPH_OIDC_EMAIL_CLAIM=email             # identity claim (default: email)
# export POLYGRAPH_OIDC_REQUIRE_MFA=1                 # require an MFA amr/acr claim
```

Clients send the IdP-issued JWT as `Authorization: Bearer <token>`. The service
verifies the signature against the IdP's JWKS (with issuer/audience/expiry
checks), then maps the token's identity (its `email`/`sub`) to a **workspace
member's role** — so add users with `POST /api/members` first. A user who is a
member of several workspaces selects one with an `X-Workspace: <id>` header
(otherwise the first is used). An authenticated user who is not a member of any
workspace is denied (`403`).
