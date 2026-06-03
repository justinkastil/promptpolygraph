# Deploying PromptPolygraph (the service)

PromptPolygraph ships as **one container image with two roles**:

| Role   | Command            | Purpose                                                        |
| ------ | ------------------ | -------------------------------------------------------------- |
| api    | `polygraph-server` | FastAPI app (uvicorn) on `POLYGRAPH_PORT` (default `8080`).    |
| worker | `polygraph-worker` | Claim-loop worker that executes enqueued jobs.                 |

The API enqueues jobs to a database; workers claim and run them. The same image
runs both — you choose the role by overriding the container command.

## Reports / artifacts

- `html`, `md`, and the run `summary` are **re-rendered from the database** by
  the API, so they survive instance churn and need no shared storage.
- `docx` and `pdf` reports are **read from `OUT_DIR`**. In a multi-container
  deploy the api and worker must **share a volume mounted at `OUT_DIR`** so the
  API can serve artifacts a worker wrote.
- **PDF export uses LibreOffice (`soffice`)**, which the default image already
  includes (`html`/`md`/`docx` do not need it). For a smaller image without PDF,
  build with `docker build --build-arg INCLUDE_PDF=false .`.

## Key environment variables (prefix `POLYGRAPH_`)

| Var                 | Notes                                                              |
| ------------------- | ------------------------------------------------------------------ |
| `DATABASE_URL`      | `sqlite:///...` (dev) or `postgresql+psycopg://user:pw@host/db`.   |
| `API_KEYS`          | Comma-separated keys. Empty disables auth (dev only).              |
| `OUT_DIR`           | Report-artifact directory. Default `/data/out` in the image.       |
| `CONFIG_DIR`        | Named-config directory. Default `/app/configs` in the image.       |
| `INPROCESS_WORKER`  | `true` runs a worker thread inside the API; set `false` for multi-container. |
| `SCHEDULES_PATH`    | YAML of cron schedules; when set the API starts a scheduler.       |
| `WEBHOOK_URL`       | Optional global webhook fired on every run completion.             |
| `DEFAULT_MOCK`      | `true` runs offline (no model calls).                              |
| `ANTHROPIC_API_KEY` | Required only for real (non-mock) runs. Not `POLYGRAPH_`-prefixed. |

---

## Local — Docker Compose

```sh
# Build and start postgres + api + worker.
docker compose up --build

# Scale workers horizontally (stateless; safe concurrent claims).
docker compose up --scale worker=4
```

- API on http://localhost:8080 (health: `/healthz`, docs: `/docs`).
- Set `POLYGRAPH_API_KEYS` in your environment before `up` to enable auth;
  defaults to a placeholder dev key otherwise.
- Defaults to `POLYGRAPH_DEFAULT_MOCK=true` so it runs offline. Set
  `ANTHROPIC_API_KEY` and `POLYGRAPH_DEFAULT_MOCK=false` for live runs.
- Reports land in the shared `out` named volume (mounted at `/data/out`).
- A run with `config_name: support_bot` works out of the box (the bundled
  named config at `/app/configs/support_bot.yaml`).

---

## AWS — ECS Fargate

Sample task definition: [`aws/ecs-task-def.json`](aws/ecs-task-def.json). It
runs **both containers (api + worker) in one task**; for higher worker scale,
split into two task definitions and run the worker as its own Service with
`desiredCount > 1`.

- **Database**: use **RDS Postgres**; set `POLYGRAPH_DATABASE_URL` to its
  `postgresql+psycopg://...` URL (via Secrets Manager).
- **Shared artifacts**: mount **EFS at `OUT_DIR`** (`/data/out`) on both
  containers so docx/pdf written by the worker are served by the api.
- **Load balancer**: front the api with an **ALB**; the target-group liveness
  probe hits `/healthz` (200 `{"status":"ok"}`).
- **Secrets**: inject `POLYGRAPH_DATABASE_URL`, `POLYGRAPH_API_KEYS`, and
  `ANTHROPIC_API_KEY` via **SSM Parameter Store / Secrets Manager** — never
  bake them into the image.
- The api sets `POLYGRAPH_INPROCESS_WORKER=false`; the worker container handles
  jobs.

**Simplest single-service option — App Runner.** Run only the api with
`POLYGRAPH_INPROCESS_WORKER=true` (api works its own jobs) against RDS Postgres.
No separate worker, no EFS needed if you only export html/md.

**Scale option — EKS.** Run api and worker as separate Deployments, scale the
worker Deployment's replica count, and use an EFS-backed PVC at `OUT_DIR`.

---

## GCP — Cloud Run

Sample service manifest: [`gcp/cloudrun-api.yaml`](gcp/cloudrun-api.yaml).

```sh
gcloud run services replace deploy/gcp/cloudrun-api.yaml --region us-central1
```

- **Database**: **Cloud SQL Postgres** via the built-in connector
  (`run.googleapis.com/cloudsql-instances` + a unix-socket `DATABASE_URL`).
- **Worker**: for simple setups keep `POLYGRAPH_INPROCESS_WORKER=true` on the
  api. For scale, set it `false` and deploy a **separate Cloud Run *service***
  for the worker with **`min-instances >= 1`** (Cloud Run Jobs are batch, not a
  long-lived claim loop).
- **Ephemeral filesystem**: Cloud Run instances have no shared disk, so rely on
  the DB-rendered `html`/`md` + summary. Durable `docx`/`pdf` should be pushed
  to **GCS** (future work); per-instance `OUT_DIR` is not shared across
  instances.
- **Secrets**: reference `POLYGRAPH_API_KEYS` and `ANTHROPIC_API_KEY` from
  **Secret Manager** (`secretKeyRef`); do not bake them into the image.
- Health: startup + liveness probes hit `/healthz`.

---

## Scaling

- Workers are **stateless** — scale them horizontally (more containers /
  replicas / instances). No coordination needed beyond the database.
- On Postgres, job claiming uses **`SELECT ... FOR UPDATE SKIP LOCKED`**, so
  concurrent workers never claim the same job.
- The api can also run a worker in-process (`POLYGRAPH_INPROCESS_WORKER=true`)
  for the simplest single-process deployments.

## Secrets & auth

- Set `POLYGRAPH_API_KEYS` to a comma-separated list to require an API key on
  requests. An empty value disables auth and is for local dev only.
- **Never bake keys into the image.** Provide `POLYGRAPH_API_KEYS`,
  `POLYGRAPH_DATABASE_URL`, and `ANTHROPIC_API_KEY` at runtime via your
  platform's secret store (SSM / Secrets Manager / Secret Manager) or, locally,
  via environment / `.env`.
