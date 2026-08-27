# Mission

Deliver open GitHub issues **#54**, **#55**, **#56**, and **#57** on this
existing product repository (`justinkastil/promptpolygraph`).

This is a real shipped product. Do not rewrite it. Do not deploy. Do not
push. Do not add paid dependencies. Do not run live red-team against any
system you do not own. Do not regress #58/#59.

## #54 — Job retry/backoff and dead-letter handling

`job_max_attempts` defaults to 1 and the worker marks failed jobs
`status='failed'` with no re-enqueue, despite a `job.attempts` column.
A transient blip kills a multi-hour run with no recovery.

- Exponential-backoff retry up to a configurable cap.
- Queryable dead-letter list at `GET /api/jobs/dead-letter`.
- Manual retry at `POST /api/jobs/{job_id}/retry`.
- Expose `promptpolygraph.service.retry.record_failure(store, job_id, error)`
  returning the updated job dict, including `backoff_seconds` or
  `next_retry_at` while retries remain.

## #55 — Graceful shutdown / in-flight job draining

On SIGTERM the worker stops polling and the API lifespan shuts the
scheduler with `wait=False`; no drain of the executing job.

- Add a drain flag: stop claiming, wait up to N seconds for running jobs,
  log a shutdown summary, flip readiness=false at drain start.
- Keep `/healthz` as liveness (200 during drain).
- `/healthz/ready` returns **503** once drain has begun.
- Expose `promptpolygraph.service.shutdown.begin_drain()` and
  `promptpolygraph.service.shutdown.summary() -> dict`.

## #56 — DB connection-pool config and query/statement timeouts

`create_engine(url)` is called with no pool_size/max_overflow/pool_recycle/
connect_timeout and no per-statement timeout.

- Add Settings: `db_pool_size`, `db_max_overflow`, `db_pool_recycle`,
  `db_connect_timeout`, `db_statement_timeout`.
- Apply them when constructing the engine.
- Expose `promptpolygraph.service.db.engine_kwargs(settings, url) -> dict`
  so a Postgres URL includes pool keys, a connect timeout, and a
  statement timeout.

## #57 — Backup/restore helper and data-retention/GC policy

Runs/jobs persist forever; SQLite has no backup automation; SERVICE.md
does not specify RDS backup cadence/WAL retention.

- Settings: `job_retention_days`, `run_retention_days`.
- Scheduled/callable cleanup (soft-delete or purge of aged rows).
- `promptpolygraph.service.retention.purge(store)` removes or archives
  aged jobs/runs.
- `promptpolygraph.service.backup.create_snapshot(store, dest=...)`
  produces a restorable snapshot file.
- Document RDS snapshot/WAL retention in `docs/SERVICE.md`.
- Use DELETE/UPDATE of aged rows. Do not DROP TABLE.

## Rules

- Existing pytest suite must stay green.
- `scripts/accept_gh58_59.py` and `scripts/accept_gh54_57.py` stay frozen.
- You invent tests under `tests/`.
- Stay inside the service/worker/db/queue/docs surface. No OIDC, no SCIM,
  no ticketing, no container-signing, no public publish.
