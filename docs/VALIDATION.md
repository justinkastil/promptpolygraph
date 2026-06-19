# Validation

PromptPolygraph ships a regenerable **validation package**: a command that
qualifies the installation, exercises each component on golden inputs, and
confirms a run reproduces a reference result — emitting a timestamped evidence
bundle a reviewer can keep on file.

```bash
polygraph validate --out evidence/
```

This writes `evidence/evidence.json` (machine-readable) and `evidence/evidence.md`
(human-readable), and exits non-zero if any check fails. It runs fully offline
(mock mode) and is deterministic.

## What each qualification proves

### IQ — installation qualification
The environment can run the tool as specified: a supported Python, the required
dependencies import, the bundled data (the persona library, the reference lock,
the judge-calibration set) is packaged, and the pinned OWASP/MITRE-ATLAS mapping
matches its committed checksum.

### OQ — operational qualification
Each component produces the expected output on golden inputs:

- the statistics primitives (e.g. the Wilson interval against a known value);
- corpus + adapter + analyzer + gate over a deterministic mini-run, producing a
  well-formed summary (with the confidence + gate-band layers);
- the report renderers — Markdown, HTML, and **valid JUnit + SARIF 2.1.0**;
- the red-team loop, producing an ASR with a confidence interval;
- judge calibration, producing a metric set against the labeled ground truth.

### PQ — performance qualification
A full in-process run is repeated and must reproduce **byte-for-byte** (mock mode
is deterministic), demonstrating run-over-run reproducibility.

## Related trust surfaces

These stand alone and also back the bundle above:

- **Reference integrity** — `polygraph references --check` fails if the
  technique→OWASP/ATLAS mapping drifts from `data/references.lock.json` or any
  technique is unmapped. Run in CI.
- **Provenance** — every run can emit a manifest of what produced it
  (`polygraph manifest --run <id>`; red-team runs write one automatically):
  tool + dependency versions, run fingerprints, and the probe sources used with
  their package versions and the standards mapping hash.
- **Judge calibration** — `polygraph calibrate` scores the breach judge against
  a labeled set (precision/recall/F1 + Cohen's κ) so you know whether to trust
  the judge before you gate on it. `--min-f1` makes it a CI gate.
- **Statistical rigor** — proportions (ASR, pass rates) carry Wilson confidence
  intervals; regressions are significance-tested (Benjamini-Hochberg-corrected);
  the gate can decline to fail inside the noise band (`analyze.respect_ci`).

## In CI

```bash
polygraph validate                       # exits non-zero on any IQ/OQ/PQ failure
polygraph references --check             # standards-mapping integrity
polygraph calibrate --mock --min-f1 0.7  # judge-reliability gate (use a real backend to publish)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) §6 for the full trust-and-validation
surface and what remains for the 1.0 release.
