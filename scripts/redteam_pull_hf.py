#!/usr/bin/env python3
"""Download the `backend: hf` (and `backend: mlx`) models in the roster.

For AUTHORIZED red-teaming of a system you own. The models named in
``redteam-models.yaml`` are mainstream open-weight instruct models that power
the attacker / judge roster; the actual attack corpora come from separate OSS
tooling.

This pulls raw weights from the HuggingFace Hub via ``snapshot_download`` so you
can serve them locally (vLLM / TGI / transformers / mlx_lm). ``huggingface_hub``
is an *optional* dependency — it is imported lazily and, if missing, the script
prints a clear install hint instead of crashing.

Usage:
    python scripts/redteam_pull_hf.py                 # download all hf/mlx entries
    python scripts/redteam_pull_hf.py --dry-run       # list what would download
    python scripts/redteam_pull_hf.py --manifest path/to/redteam-models.yaml
    python scripts/redteam_pull_hf.py --local-dir ./models   # where to place files

License: each repo carries its own license (Apache-2.0, Llama Community, etc.).
Review and accept it on the model's HuggingFace page before downloading. Gated
repos require `huggingface-cli login`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "redteam-models.yaml"


def _load_hf_entries(manifest: Path) -> list[dict]:
    """Return manifest entries whose backend is `hf` or `mlx`."""
    try:
        import yaml
    except Exception:
        print(
            "ERROR: PyYAML is required to read the manifest. Install it with:\n"
            "    pip install pyyaml",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if not manifest.is_file():
        print(f"ERROR: manifest not found: {manifest}", file=sys.stderr)
        raise SystemExit(1)

    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []

    out: list[dict] = []
    for m in models:
        if isinstance(m, dict) and m.get("backend") in ("hf", "mlx"):
            out.append(m)
    return out


def _print_entry(entry: dict) -> None:
    name = entry.get("name", "?")
    repo = entry.get("hf_repo", "(no hf_repo set!)")
    backend = entry.get("backend", "hf")
    params = entry.get("params", "?")
    min_ram = entry.get("min_ram_gb", "?")
    print(f"  - {name}  [{backend}]  repo={repo}")
    print(f"      params={params}  min_ram_gb={min_ram}")
    notes = entry.get("notes")
    if notes:
        print(f"      notes: {notes}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Download backend: hf / mlx models from the red-team roster."
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="path to redteam-models.yaml (default: repo root)",
    )
    ap.add_argument(
        "--local-dir",
        type=Path,
        default=None,
        help="directory to download into (default: HuggingFace cache)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be downloaded (incl. min_ram) without downloading",
    )
    args = ap.parse_args(argv)

    entries = _load_hf_entries(args.manifest)

    print("PromptPolygraph — local red-team roster: HuggingFace pull")
    print(f"  manifest: {args.manifest}")
    print()

    if not entries:
        print("No backend: hf or backend: mlx entries found. Nothing to download.")
        print("(Ollama models are handled by scripts/redteam_pull_ollama.sh.)")
        return 0

    if args.dry_run:
        print("DRY RUN — the following models WOULD be downloaded:")
        total_ram = 0.0
        for e in entries:
            _print_entry(e)
            try:
                total_ram = max(total_ram, float(e.get("min_ram_gb") or 0))
            except (TypeError, ValueError):
                pass
        print()
        print(f"Peak single-model memory to serve any of these: ~{total_ram:g} GB")
        print("Reminder: review each repo's LICENSE on its HuggingFace page first.")
        return 0

    # Real download path — lazy import so --dry-run never needs the dep.
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        print(
            "ERROR: huggingface_hub is not installed (it is an optional dep).\n"
            "Install it with:\n"
            "    pip install huggingface_hub\n"
            "Then re-run this script. Use --dry-run to preview without it.",
            file=sys.stderr,
        )
        return 2

    print("Reminder: review + accept each repo's LICENSE before use.")
    print("Gated repos require: huggingface-cli login")
    print()

    failures = 0
    for e in entries:
        name = e.get("name", "?")
        repo = e.get("hf_repo")
        if not repo:
            print(f"  SKIP {name}: no hf_repo set", file=sys.stderr)
            failures += 1
            continue

        local_dir = None
        if args.local_dir is not None:
            local_dir = str(args.local_dir / name)

        print(f">>> downloading {name}  ({repo})")
        try:
            path = snapshot_download(repo_id=repo, local_dir=local_dir)
            print(f"    ok: {path}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"    FAILED: {repo}: {exc}", file=sys.stderr)
            failures += 1
        print()

    if failures:
        print(f"Done with {failures} failure(s).", file=sys.stderr)
        return 1

    print("All HuggingFace models downloaded. See docs/REDTEAM_LOCAL.md to serve them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
