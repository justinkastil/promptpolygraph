# Contributing

Thanks for your interest in PromptPolygraph. This guide covers the dev setup,
the conventions, and how changes get reviewed. It mirrors
[`CONTRIBUTING.md`](https://github.com/justinkastil/promptpolygraph/blob/main/CONTRIBUTING.md)
at the repo root.

## Development setup

```bash
python -m pip install -e ".[dev,service]"     # core + tests + service
# optional extras as needed:
#   .[llm]      OpenAI-compatible adapter
#   .[redteam]  OSS attack sources (garak, PyRIT, DeepTeam, datasets)
#   .[crypto]   Ed25519 signing
#   .[oidc]     OIDC/SSO
pytest -q                                      # full suite (offline, no API key)
```

Everything runs offline in `--mock` mode with deterministic stand-ins, so the
tests need no network and no tokens.

## Conventions

- **Python 3.10+**, `from __future__ import annotations`, pydantic v2.
- **Additive changes.** The summary dict, report formats, and gate verdicts are a
  contract — add keys, don't break existing ones. New behavior should default to
  the prior behavior unless opted in.
- **Tests first-class.** Add tests with every change; numerics are checked
  against reference values. Keep the suite green and offline-deterministic.
- **Offline determinism.** A `mock` path must exist for anything that would
  otherwise call a model or the network; mock output must be byte-stable.
- **Docs with the change.** Update the README, `CHANGELOG.md` (`[Unreleased]`),
  and any relevant `docs/` page in the same PR.
- **Commit/PR messages are factual** — what changed and why, no marketing.

## Extending the tool

The extension points (see [Architecture](ARCHITECTURE.md) §4):

| Add… | Implement |
|---|---|
| a target system | an `Adapter` |
| an evaluation signal | an assertion scorer |
| an attacker team | a `RedTeamProfile` |
| an attack technique | a `Technique` in the catalog (keep the OWASP/ATLAS lock current: `polygraph references --write`) |
| a probe source | an `AttackSource` |
| a report format | a renderer |

## Security and responsible use

Red-team capabilities are for authorized testing only — read
[`RESPONSIBLE_USE.md`](https://github.com/justinkastil/promptpolygraph/blob/main/RESPONSIBLE_USE.md).
Report vulnerabilities privately per
[`SECURITY.md`](https://github.com/justinkastil/promptpolygraph/blob/main/SECURITY.md),
not in a public issue.

## Pull requests

- Branch from `main`; keep PRs focused.
- Ensure `pytest -q`, `polygraph references --check`, and `polygraph validate`
  pass (CI runs all three).
- Describe what changed and why; link the issue. A maintainer reviews and merges
  (see [`GOVERNANCE.md`](https://github.com/justinkastil/promptpolygraph/blob/main/GOVERNANCE.md)).
