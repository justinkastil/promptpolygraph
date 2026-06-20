# Threat model

PromptPolygraph generates adversarial prompts, sends them to a system under
test, reads model output (and optionally a local source checkout), and writes
reports. This document states the trust boundaries, the assets, the risks, and
the controls that mitigate them. It is scoped to the tool itself — not the
security of the system being evaluated.

## Assets

- **The system under test** and its credentials (adapter URL, API keys/headers).
- **Target responses**, which may contain sensitive content elicited by a probe.
- **Local source** read by the code-grounded red-team trace / forensic audit.
- **Run records and reports** (the evidence an institution acts on).
- **Backend credentials** for the judge/audit/generation model.

## Trust boundaries

```
operator ──> PromptPolygraph (local process / CI runner / container)
                 │  adapter.query()        ──> system under test (network)
                 │  judge/audit/gen client ──> LLM backend (local or remote)
                 │  code-dive (optional)   ──> local source checkout
                 └─ store + reports        ──> local disk / SQL
```

The engine is the trust boundary. Everything crossing it outward — the target,
the backend, the disk — is treated explicitly below.

## Risks and controls

### R1 — Adversarial content handling
The tool *produces* jailbreak/injection probes by design. They are benign
security-testing templates, not weaponized payloads, and the catalog ships
standard, well-known techniques. Reports frame output as a vulnerability finding
with a mitigation, not reusable attack content. **Use is gated on owning (or
being authorized to test) the target** — stated in the red-team output header.

### R2 — Source/IP leakage during a code dive
The code-grounded root-cause trace reads a local checkout. Controls:
- **Local model by default** (`redteam.code_dive_provider` defaults to a local
  Ollama), so source never leaves the machine.
- **Air-gap** (`POLYGRAPH_AIR_GAP=1` / `redteam.air_gap`) hard-refuses any
  non-local provider for a code dive.
- **Explicit consent** is required before any remote provider sees excerpts.
- **Secret scrubbing** runs over excerpts before they are sent to a model.
- **`.gitignore` / `.polygraphignore`** and a vendor-dir skip bound what is
  indexed.

### R3 — Sensitive data in target responses
Responses are stored and rendered verbatim. A response/export/cache redaction
pass and data-residency controls are the planned generalization (the secret
scrub above is the current primitive). Until then, treat the store and reports
as containing whatever the target returned, and run locally for sensitive
targets.

### R4 — Custom-code execution (assertions)
`python`/`callable` assertion scorers can run user code. They are **disabled by
default** (`scorers.sandbox: disabled`); `expr` restricts to an AST-checked
expression, and `subprocess` isolates with a timeout. Never enable an untrusted
config's custom-code scorers.

### R5 — Backend credentials
API keys are read from the environment (`${VAR}` indirection in adapter config),
never written to run records or reports. Local providers need no key.

### R6 — Report/record tampering
Reports and run records are the basis for decisions, so integrity matters.
Controls: a sealed bundle (`polygraph bundle`) carries a SHA-256 manifest of
every file and **`polygraph verify` refuses on any tampered/missing/extra file**.
Signatures add origin authentication: an HMAC shared secret
(`POLYGRAPH_SIGNING_KEY` / `--hmac-key`) within one trust domain, or — with the
`[crypto]` extra — an **Ed25519 keypair** (`polygraph keygen`, `bundle
--sign-key`, `verify --pub-key`) so an external auditor verifies with the public
key alone. Run records are schema-versioned and migrated forward on read.
Privileged actions can be written to a **hash-chained audit log** (`audit_log`)
whose `verify_chain` makes any alteration or deletion detectable. Provenance
manifests record what produced each result.

### R7 — Reference / standards drift
A finding cites OWASP/MITRE-ATLAS categories. The mapping is pinned behind a
checksum (`data/references.lock.json`); `polygraph references --check` (run in
CI) fails on drift or any unmapped technique, so a tag cannot silently change
what a finding claims.

### R8 — Supply chain
Optional OSS attack sources (garak/PyRIT/DeepTeam/datasets) and datasets are
*not* bundled and register only when their dependency imports. The provenance
manifest records each source's package version. Pin versions and review the
optional extras you install.

### R9 — Untrusted bundle extraction
`polygraph unbundle` extracts a tar archive. On Python 3.12+ it uses the `data`
filter to reject path-escaping members. Only unbundle archives you trust, and
prefer `verify` first.

## Out of scope

The security of the system under test; network transport security to the target
(use TLS endpoints); multi-tenant isolation and authn/z for the shared service
deployment (tracked for 1.0 — see the v1.0 epic).
