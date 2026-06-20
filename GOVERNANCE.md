# Governance

This document describes how PromptPolygraph is maintained and how decisions are
made. It is intentionally lightweight and will grow with the project.

## Roles

- **Maintainers** review and merge changes, cut releases, and set direction.
  They are responsible for the trust properties the project claims (see the v1.0
  validation epic and [docs/VALIDATION.md](docs/VALIDATION.md)).
- **Contributors** propose changes via pull requests (see
  [CONTRIBUTING.md](CONTRIBUTING.md)). Anyone may contribute.

## Decision-making

- Routine changes are approved and merged by a maintainer after review, with a
  green CI run (tests, reference integrity, validation package).
- Substantive or trust-affecting changes (the statistical methods, the
  standards mapping, the integrity/signing or auth model) require a maintainer
  review that explicitly considers the effect on the documented trust surface.
- Disagreements are resolved by maintainer consensus; the goal is the most
  correct, defensible behavior, not the fastest merge.

## Releases

- [Semantic Versioning](https://semver.org/). User-facing changes land in
  `CHANGELOG.md` under `[Unreleased]` and are dated at release.
- A release is a tagged GitHub Release; publishing to PyPI is automated via
  trusted publishing (OIDC) on release.
- The validation package (`polygraph validate`) and reference-integrity check run
  in CI; a release should not ship with either failing.

## Standards & data integrity

- The OWASP/MITRE-ATLAS technique mapping is pinned behind a checksummed lock
  (`data/references.lock.json`); changes to it are deliberate and reviewed, and
  CI fails on undeclared drift.
- Bundled datasets/probes are benign templates; adversarial datasets are fetched
  on demand and opt-in (see [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md)).

## Security

Vulnerabilities are reported privately per [SECURITY.md](SECURITY.md) and handled
by maintainers before public disclosure.
