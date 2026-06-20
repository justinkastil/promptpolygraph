# Security policy

## Reporting a vulnerability

Report suspected security issues privately via GitHub's **"Report a
vulnerability"** (Security → Advisories) on the repository, rather than opening a
public issue. Please include a description, affected version, and reproduction
steps. We aim to acknowledge a report within a few business days.

## Supported versions

Security fixes target the latest released minor version. Pin a version in
production and review the [CHANGELOG](CHANGELOG.md) before upgrading.

## Scope and safe use

PromptPolygraph generates adversarial prompts and runs an authorized red team
against a system **you own or are authorized to test**. It is a defensive
evaluation tool; the catalog ships standard, benign security-testing templates,
and reports present findings with mitigations, not reusable attack content.

Operational security controls and trust boundaries are documented in
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). In particular:

- Custom-code assertion scorers are **disabled by default**; only enable them for
  a config you trust.
- The code-grounded trace defaults to a **local model**; `POLYGRAPH_AIR_GAP=1`
  hard-refuses remote providers for a code dive, and excerpts are secret-scrubbed.
- Treat the run store and reports as containing whatever the target returned; run
  locally for sensitive targets.
- Verify sealed bundles (`polygraph verify`) before acting on or extracting them.
