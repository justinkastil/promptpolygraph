# Mission

Deliver open GitHub issues **#58** and **#59** on this existing product
repository (`justinkastil/promptpolygraph`, v1.2.0).

This is a real shipped product. Do not rewrite it. Do not deploy. Do not
push. Do not add paid dependencies. Do not run live red-team against any
system you do not own.

## #58 — Startup validation of config dependencies

The service boots with `ANTHROPIC_API_KEY` unset and fails only when a
live job runs. `CONFIG_DIR` / `SCHEDULES_PATH` are not validated.

- Add a startup check (`--validate-config` and/or `model_post_init`):
  keys present (or mock=true), configs load, schedules parse, optional
  LLM ping.
- Fail boot on critical issues; warn on the rest.
- Expose a callable `promptpolygraph.service.startup_validate.run` that
  returns `(ok: bool, report: list[dict])` with per-check
  `status` in `{pass, warn, fail}`.

## #59 — Readiness probe

`/healthz` only confirms the process is alive. Add `/healthz/ready`
that checks the store (`SELECT 1` or equivalent), optional LLM
reachability, and queue not over-full. Return **503** on failure.
Keep `/healthz` as liveness. Document the pair for Kubernetes in
`docs/SERVICE.md` if that file already describes `/healthz`.

## Rules

- Existing pytest suite must stay green.
- Do not weaken `scripts/accept_gh58_59.py`.
- You invent tests under `tests/`.
- Stay inside the service/startup/health surface. No OIDC, no SCIM, no
  ticketing, no container-signing, no public publish.
