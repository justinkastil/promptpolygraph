# Running PromptPolygraph in CI

PromptPolygraph runs as a pipeline gate: it validates the config, scores a run,
fails the build on a regression, and emits machine-readable reports that the CI
renders in its test and security tabs.

## Quick start

Generate a starter pipeline for your CI:

```bash
polygraph scaffold-ci github      # .github/workflows/promptpolygraph.yml
polygraph scaffold-ci gitlab      # .gitlab-ci.yml
polygraph scaffold-ci jenkins     # Jenkinsfile
polygraph scaffold-ci precommit   # .pre-commit-config.yaml
```

Pass `--config-path path/to/config.yaml` to point the generated steps at your
config. The scaffolds run in `--mock` mode out of the box; drop `--mock` and set
a backend (e.g. `ANTHROPIC_API_KEY`, or a local Ollama provider) once an adapter
points at a real system.

## The gate

```bash
polygraph validate-config --config config.yaml          # fail fast on a bad config
polygraph all       --config config.yaml --format md,html
polygraph analyze   --config config.yaml --run "$RUN" --ci \
    --baseline rolling:5 --github-annotations --pr-comment pr.md
```

- `--ci` exits non-zero when the gate fails (per-dimension threshold, cumulative
  across categories).
- `--baseline` compares against a prior run — a run id, `rolling:N` (median of
  the N most-recent comparable runs), or `HEAD` (the most recent comparable run).
  Regressions are flagged statistically (a two-sample test with a
  Benjamini-Hochberg correction across dimensions), so a within-noise change is
  reported but not flagged as a regression.
- `--github-annotations` prints `::error` / `::warning` workflow commands and
  writes a job summary (`$GITHUB_STEP_SUMMARY`).
- `--pr-comment PATH` writes a markdown summary (verdict, per-category table,
  assertion-pass-rate confidence interval, baseline movement) to post on the PR.

Set `analyze.respect_ci: true` in the config to have the gate return
*inconclusive* (and not fail the build) when the threshold falls inside a
metric's confidence interval — i.e. when the run has not gathered enough samples
to call it. The point estimate gate is the default.

## Machine-readable reports

```bash
polygraph report  --config config.yaml --run "$RUN" --format junit,sarif
polygraph redteam --config config.yaml --format md,sarif,junit
```

- **JUnit XML** (`report.junit.xml`) — categories map to test suites, cases (or
  red-team attempts) to test cases; a gate failure or breach is a test failure.
  GitHub, GitLab, Jenkins, and CircleCI parse this into per-suite results.
- **SARIF 2.1.0** (`report.sarif.json`) — findings render inline on a PR via
  GitHub/GitLab code scanning. Each failing case or red-team vulnerability is a
  result with a severity-mapped level; a code-grounded red-team trace attaches a
  `file:line` location.

Upload SARIF with `github/codeql-action/upload-sarif@v3` (the generated GitHub
workflow does this) to surface findings in the Security tab.

## Sharding a large corpus

A run is durable and `--resume`-able, and concurrency (not a work queue) drives
throughput, so thousands of prompts fit a single CI job. For very large corpora,
split the run across matrix jobs by category (`--categories a,b,c`) and merge the
reports, or move to [service mode](SERVICE.md) for a worker pool.

## Editor validation

```bash
polygraph schema --out schemas/
```

Add `# yaml-language-server: $schema=./schemas/config.schema.json` to the top of
a config for autocomplete and inline validation in any YAML-LS editor.
