# Supply chain security

PromptPolygraph ships build provenance attestations, a CycloneDX SBOM, and a
CVE/license scan gate in CI. This document describes what is produced and how to
verify it.

## What is produced

| Artifact | Where | When |
| --- | --- | --- |
| CVE scan (`pip-audit`) | CI `audit` job log | every push / PR |
| CycloneDX SBOM (`sbom.cdx.json`) | CI `build` job artifact `sbom`; GitHub release asset | every push / PR; on release |
| Build provenance attestation | GitHub attestations API | on release |
| PEP 740 publish attestations | PyPI | on release |

## CVE / dependency scan

The `audit` job in `.github/workflows/ci.yml` installs the full dependency set
(all extras) and runs `pip-audit` against the OSV database. Any reported
vulnerability fails the build.

Triaged findings that are accepted (no fix available, not reachable) go in
`.pip-audit-ignore` at the repo root: one OSV/PYSEC/GHSA vulnerability ID per
line, `#` for comments. The file is empty by default. Each entry should carry a
comment justifying why it is accepted.

## SBOM

The SBOM is generated with [`cyclonedx-bom`](https://pypi.org/project/cyclonedx-bom/):

```bash
pip install -e . cyclonedx-bom
cyclonedx-py environment --output-format JSON --outfile sbom.cdx.json
```

It enumerates the resolved transitive dependency tree (CycloneDX 1.x JSON),
including each component's version and license metadata, which doubles as a
license inventory.

- In CI it is uploaded as the `sbom` build artifact.
- On a release it is attached as the `sbom.cdx.json` release asset.

Download the release SBOM:

```bash
gh release download <tag> --pattern sbom.cdx.json --repo justinkastil/promptpolygraph
```

## Verifying build provenance

Releases carry a GitHub build-provenance attestation (SLSA) over the wheel and
sdist. Download an artifact and verify it against this repository:

```bash
# From PyPI or the GitHub release, then:
gh attestation verify ./promptpolygraph-<version>-py3-none-any.whl \
    --repo justinkastil/promptpolygraph
```

A successful verification confirms the artifact was built by this repository's
`publish` workflow and has not been altered.

## Verifying PyPI attestations

`pypa/gh-action-pypi-publish` publishes PEP 740 attestations alongside the
package. Modern installers can verify them at install time; the attestations are
also visible on the PyPI project page under each release's files.
