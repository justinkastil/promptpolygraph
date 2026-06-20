# CLI

The package installs a single entry point, `polygraph`, with subcommands grouped
by phase of the workflow. Run `polygraph <command> --help` for the full,
authoritative flags of any command.

```bash
polygraph --help
polygraph all --help
```

## End-to-end

| Command | Purpose |
| --- | --- |
| `all` | Run the full pipeline: generate, run, score, persona, audit, report. |
| `run` | Execute the corpus against the configured adapter and score it. |
| `generate` | Build a synthetic corpus (fixed, varied, or adversarial). |
| `report` | Render a scored run as markdown / docx / pdf / html. |
| `dashboard` | Serve the local interactive dashboard. |

## Configuration and scaffolding

| Command | Purpose |
| --- | --- |
| `init` / `new` | Scaffold a config and example pack. |
| `scaffold-ci` | Emit a CI workflow that runs the gate. |
| `tune` | Generate a tailored example pack for a target. |
| `validate-config` | Statically validate a `config.yaml`. |
| `schema` | Emit the JSON Schema for the config. |
| `personas` / `profiles` | Inspect persona and profile definitions. |

## Analysis

| Command | Purpose |
| --- | --- |
| `analyze` | Inspect a stored run. |
| `compare` | Comparability-gated comparison across N runs. |
| `trend` | Per-dimension trends over time. |
| `regressions` | Detect regressions vs a baseline. |
| `power` | Statistical power / sample-size helper. |
| `calibrate` | Calibrate judge / scorer thresholds. |

## Red-team

| Command | Purpose |
| --- | --- |
| `redteam` | Run the red-team arena against the target. |
| `elicit` | Run elicitation probes. |
| `interview` | Interactive interview of the target. |

See the [Red-team](REDTEAM_LOCAL.md) operator guide for the roster and sources.

## Provenance and supply chain

| Command | Purpose |
| --- | --- |
| `bundle` | Package a run bundle. |
| `manifest` | Emit / inspect a run manifest. |
| `verify` | Verify a signed bundle or attestation. |
| `keygen` | Generate signing keys. |
| `finalize` | Seal a run for archival. |
| `audit-log` | Inspect the tamper-evident audit log. |
| `export` | Export run data. |

## Extensions

| Command | Purpose |
| --- | --- |
| `plugins` | List discovered third-party adapters and sources. |
| `references` | List configured reference systems. |

See [Plugins](PLUGINS.md) for the extension contract and [Providers](PROVIDERS.md)
for LLM backend selection.
