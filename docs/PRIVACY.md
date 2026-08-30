# Privacy: residency, PII redaction, and retention

PromptPolygraph stores prompts, model responses, and scores so that runs can be
re-read, compared, and exported. This page documents the three controls that
govern that stored data:

1. **Data residency** — a recorded, validated statement of *where* an operator
   has committed to keeping the data.
2. **PII redaction** — email addresses and US-SSN shapes are scrubbed out of
   stored response bodies at ingest, and can additionally be scrubbed on export.
3. **Retention** — an operator-invoked garbage collector that deletes aged rows.

Read the boundaries as stated. Each section is explicit about what the control
does *not* do; those are documented limits, not oversights.

---

## 1. Data residency

### The setting

| | |
| --- | --- |
| Setting | `Settings.data_residency` (`promptpolygraph.service.settings`) |
| Allowed values | `eu`, `us`, `none` |
| Default | `none` |
| Environment override | `POLYGRAPH_DATA_RESIDENCY` |

The service reads all configuration from environment variables under the
`POLYGRAPH_` prefix (and from a `.env` file when present), so:

```bash
export POLYGRAPH_DATA_RESIDENCY=eu     # or: us, none
```

Values are normalised before validation: surrounding whitespace is stripped and
the value is lower-cased, so `EU`, ` eu `, and `eu` are the same setting. An
unset or empty value means "no commitment" and resolves to the default `none`.

An **unrecognised** value is rejected — `POLYGRAPH_DATA_RESIDENCY=eur` fails
settings validation and the process does not start. This is deliberate: an
operator who typed `eur` intended a guarantee, and silently downgrading the typo
to `none` would be the wrong failure mode.

The default is `none` rather than a region because `none` asserts no guarantee,
whereas defaulting to `eu` or `us` would have the product claim a region that
the underlying storage may not honour.

### What this setting does *not* do

**`data_residency` is recorded and validated configuration. It does not
currently gate a storage path and it does not refuse a region.** Specifically:

- It does **not** route reads or writes to region-specific storage.
- It does **not** inspect `POLYGRAPH_DATABASE_URL` or `POLYGRAPH_OUT_DIR` and
  reject a database or output directory that is outside the declared region.
- It does **not** block requests, jobs, or exports on residency grounds.
- Setting it to `eu` on a deployment whose database lives in `us-east-1`
  produces **no error** — the setting simply records a claim that the
  infrastructure does not back.

Placing data in-region is the operator's job, done by pointing
`POLYGRAPH_DATABASE_URL` and `POLYGRAPH_OUT_DIR` at in-region storage. The
setting exists so that a deployment's committed region is a single declared,
validated, auditable value that documentation, dashboards, and audits can read,
rather than tribal knowledge.

---

## 2. PII redaction

### Redaction on ingest of stored response bodies

Every write to the `responses` table passes through `save_response`, which is
the single chokepoint in each store:

- `promptpolygraph.runner.store` — the core file-backed SQLite store.
- `promptpolygraph.service.db` — the service store (SQLite or PostgreSQL).

Both call `promptpolygraph.service.privacy.scrub_response` before the row is
serialised, so **response bodies are redacted on ingest and never land verbatim
in the database**.

`scrub_pii(text) -> str` is the underlying primitive and redacts:

| Shape | Matched as | Replaced with |
| --- | --- | --- |
| Email address | `local@domain.tld` | `[REDACTED-EMAIL]` |
| US SSN shape | `NNN-NN-NNNN`, separated by `-` or a space | `[REDACTED-SSN]` |

Emails are matched before SSNs, so an SSN-shaped local part
(`123-45-6789@example.com`) is consumed whole by the email rule instead of being
hollowed out into a still-identifiable domain. Neither placeholder contains an
`@` or a run of digits, so `scrub_pii` is idempotent — scrubbing already-scrubbed
text changes nothing.

`scrub_pii` is total: it returns a `str` for every input and never raises. It
sits on the persistence path, where raising would convert a privacy control into
an availability incident. `None` becomes `""` (rather than the literal `"None"`,
which would fabricate a body the target never returned); `bytes` are decoded as
UTF-8 with `errors="replace"`; anything else is stringified and then scrubbed, so
a mis-typed body is still redacted rather than passed through unexamined.

### Redaction is irreversible for stored bodies

The store keeps **only** the redacted text. There is no original, no encrypted
shadow copy, and no reversible token — the pre-redaction body is not written
anywhere, so there is nothing to un-redact from. A body that reaches the
`responses` table with an email in it is stored with `[REDACTED-EMAIL]` in that
position, permanently.

The in-memory `Response` object held by the caller is **not** mutated; the scrub
produces a copy for persistence. The unredacted body therefore remains available
to the running pipeline (adapters, analyzers, judges) for the lifetime of that
process — redaction is a *storage* control, not an in-process one.

### Documented limits

These shapes are intentionally left intact:

- **A separator is required for the SSN rule.** A bare nine-digit run is far
  more often an order, invoice, or case id than an SSN, and redacting it would
  corrupt ordinary stored bodies.
- **Near misses stay intact**: over-long digit runs (`1234-56-7890`), wrong
  groupings (`12-345-6789`), and `@`-less or domain-less fragments.
- **Only the response *body* is scrubbed** — `Response.text` and the
  `Response.tokens_streamed` chunks that reconstruct it. `Response.error` and
  `Response.raw` are deliberately left alone.
- Redaction is **shape-based, not semantic**. Names, postal addresses, phone
  numbers, and free-text disclosures are not detected. Do not treat `scrub_pii`
  as a complete de-identification pass.

### `cache.data` is NOT redacted

The `cache` table stores raw responses keyed by adapter + prompt, and its `data`
column is written by `cache_put` **without** redaction. This is a deliberate
scope boundary, not a gap in coverage:

- The cache is a keyed replay of exactly what the target returned. Redacting it
  would make a cache hit differ from the live call it stands in for.
- Every cache hit is re-scrubbed on its way through `save_response` anyway, so a
  cached body still cannot reach the `responses` table unredacted.

**Operational consequence:** the `cache` table may contain unredacted PII. Treat
it with the same care as the raw target traffic — it lives in the same database
file or schema, so a snapshot, backup, or dump includes it. Operators who need a
PII-free artifact should clear the cache rows or use the redacted export path
(below) rather than shipping a raw database file. That is a `DELETE FROM cache`
decision for the operator; nothing in the product does it automatically.

### Redaction on export (opt-in `--redact`)

Export redaction is **opt-in and off by default**. With the flag off, output
bytes are identical to the pre-redaction behaviour, so existing pipelines are not
silently changed.

**CLI — prompt/corpus export:**

```bash
polygraph export --run <run-id> --out dataset.jsonl --format jsonl --redact
```

`--redact` scrubs emails and US-SSN shapes out of every string reachable in an
exported row (recursively, through nested dicts and lists) for all three
formats: `json`, `jsonl`, and `csv`. This export emits the run's **cases /
prompts**, so `--redact` is what covers PII a user typed into a prompt.

**Library — full run export:**

```python
store.export_jsonl(run_id, "run.jsonl", redact=True)
```

Available on both the `runner.store` and `service.db` stores. It dumps case +
response + score per line and re-scrubs response bodies on the way out. Bodies
written after redaction-on-ingest existed are already clean, so `redact=True` is
chiefly for rows persisted by an earlier version of the product.

Note that the `cases.jsonl` the pipeline writes into each run directory is
produced with `redact=False`. Its response bodies are still the redacted ones
read back from the `responses` table, but its **prompt/case text is not
scrubbed**. Use `polygraph export --redact` when you need scrubbed prompt text.

---

## 3. Retention

Retention garbage collection already exists and is documented here for
completeness; see also [Service](SERVICE.md).

### How it runs

```python
from promptpolygraph.service import retention
retention.purge(store)
```

`purge` is **operator-invoked**. Nothing in the product schedules it — call it
from your own scheduled task (cron, a Kubernetes CronJob, a systemd timer) at
whatever cadence your policy requires. It returns a summary dict, e.g.
`{"jobs": 12, "runs": 3}`.

### Age thresholds

| Setting | Env var | Default |
| --- | --- | --- |
| `job_retention_days` | `POLYGRAPH_JOB_RETENTION_DAYS` | `30` |
| `run_retention_days` | `POLYGRAPH_RUN_RETENTION_DAYS` | `90` |

A row is eligible when its `created_at` is older than the corresponding cutoff,
computed from the current UTC time at each invocation.

### What it removes

1. **Jobs** older than the job cutoff whose status is not `running`.
2. **Runs** older than the run cutoff that are not referenced by a `running`
   job — and, for each such run, its dependent rows in `cases`, `responses`,
   and `scores`, removed before the `runs` row itself so no orphans are left
   behind.

All of it happens inside a single transaction, so a failure part-way through
rolls back rather than leaving a half-purged run.

### What it does not touch

**Retention operates on aged *rows* only, and it never drops a table.** Row-level
`DELETE` (and, for a future soft-delete/archive variant, `UPDATE`) is the entire
mechanism; the current implementation deletes. There is no `DROP TABLE`, no
`TRUNCATE`, and no schema change anywhere on the retention path. The schema and every table survive a
purge unchanged, including on an empty database, where `purge` is a no-op
returning `{"jobs": 0, "runs": 0}`.

Additionally:

- **In-flight work is preserved.** Jobs with status `running` are skipped
  regardless of age, and a run referenced by a `running` job is protected even
  if it is past the run cutoff.
- **The `cache` table is not purged.** Cached responses are not aged out by
  `purge` — and, per the section above, cached bodies are unredacted. If your
  retention policy needs to cover the cache, clear it yourself.
- **Files on disk are not removed.** Reports and run directories under
  `POLYGRAPH_OUT_DIR` are untouched; `purge` is a database operation and file
  lifecycle is the operator's.

### Backups interact with retention

A purge cannot reach data that has already been copied into a backup. Snapshots
taken with `backup.create_snapshot(store, dest=...)` retain whatever rows —
including unredacted `cache` rows — existed when the snapshot was taken. Apply
the same retention schedule to your backup rotation, or the effective retention
period of your deployment is the backup retention period, not
`run_retention_days`.

---

## Summary

| Data | Redacted at rest? | Aged out by `purge`? |
| --- | --- | --- |
| `responses` bodies (`text`, `tokens_streamed`) | Yes — on ingest, irreversibly | Yes, with the parent run |
| `responses` `error` / `raw` | No | Yes, with the parent run |
| `cases` (prompts) | No — scrub on export with `--redact` | Yes, with the parent run |
| `scores` | No | Yes, with the parent run |
| `cache.data` | **No** | **No** |
| `jobs` | n/a | Yes, unless `running` |
| Files under `POLYGRAPH_OUT_DIR` | Bodies inside come from redacted rows | No |
