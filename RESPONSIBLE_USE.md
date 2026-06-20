# Responsible use

PromptPolygraph is a **defensive** evaluation and red-team tool. It generates
adversarial prompts to help you find and fix weaknesses in an AI system **you own
or are explicitly authorized to test**. These boundaries are part of the license
of intent for using it.

## Authorized use only

- Run the red team **only against a system you own or have written authorization
  to test.** The red-team report header states this, and every finding is framed
  as a vulnerability + mitigation, not reusable attack content.
- The technique catalog ships **benign, standard security-testing templates** —
  not weaponized payloads.
- Do not use the tool to attack third-party systems, to generate harmful content
  for distribution, or to evade another system's safety controls in production.

## Adversarial datasets are opt-in

The optional dataset sources (`dataset:advbench`, `dataset:harmbench`,
`dataset:jailbreakbench`) fetch real harmful-behaviour datasets from their
publishers on demand. To avoid pulling harmful content silently, the live fetch
is **off by default** — the source uses benign placeholder probes unless you
explicitly acknowledge the terms:

```bash
export POLYGRAPH_ACCEPT_DATASET_TERMS=1   # I am authorized and accept the dataset terms
```

You are responsible for complying with each dataset's own license and terms, and
for handling the fetched content appropriately (it is adversarial by design).

## Handling results

- Treat the run store and reports as containing whatever the target returned,
  which may include sensitive content elicited by a probe. Run locally for
  sensitive targets; see [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the
  egress, redaction, and integrity controls.
- Share vulnerability findings through responsible-disclosure channels, not
  publicly, until the owner has had a chance to remediate.

## Reporting misuse or vulnerabilities

Report security issues in the tool itself via [SECURITY.md](SECURITY.md). If you
become aware of the tool being used to attack systems without authorization,
please open an issue or contact the maintainers.
