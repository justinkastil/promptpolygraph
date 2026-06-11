#!/bin/sh
# ─── redteam_pull_ollama.sh ───────────────────────────────────────────────────
# Pull every `backend: ollama` model declared in redteam-models.yaml.
#
# For AUTHORIZED red-teaming of a system you own. These are mainstream open
# instruct models that power the attacker / judge roster.
#
# Usage:
#   sh scripts/redteam_pull_ollama.sh                # uses ./redteam-models.yaml
#   MANIFEST=path/to/redteam-models.yaml sh scripts/redteam_pull_ollama.sh
#
# Safe + idempotent: `ollama pull` re-pulls only changed layers.
set -eu

# Resolve repo root from this script's location (so it works from anywhere).
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MANIFEST=${MANIFEST:-"$REPO_ROOT/redteam-models.yaml"}

echo "PromptPolygraph — local red-team roster: Ollama pull"
echo "  manifest: $MANIFEST"
echo

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: manifest not found: $MANIFEST" >&2
  echo "       Create it (see redteam-models.yaml at the repo root)." >&2
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: 'ollama' is not installed or not on PATH." >&2
  echo "       Install from https://ollama.com/download , then re-run." >&2
  exit 1
fi

# Pick a Python to parse the YAML (prefer the project venv).
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

# Emit the ollama_tag of each `backend: ollama` entry, one per line.
TAGS=$(
  "$PY" - "$MANIFEST" <<'PYEOF'
import sys
try:
    import yaml
except Exception:
    sys.stderr.write("ERROR: PyYAML not available in the chosen Python.\n")
    sys.exit(2)
with open(sys.argv[1], encoding="utf-8") as fh:
    data = yaml.safe_load(fh) or {}
for m in (data.get("models") or []):
    if isinstance(m, dict) and m.get("backend") == "ollama":
        tag = m.get("ollama_tag")
        if tag:
            print(tag)
PYEOF
)

if [ -z "$TAGS" ]; then
  echo "No backend: ollama entries found in the manifest. Nothing to pull."
  exit 0
fi

echo "Will pull these Ollama models:"
echo "$TAGS" | sed 's/^/  - /'
echo

# Pull each tag. Continue past individual failures so one bad tag doesn't
# block the rest; track whether any failed for the exit status.
FAILED=0
echo "$TAGS" | while IFS= read -r tag; do
  [ -z "$tag" ] && continue
  echo ">>> ollama pull $tag"
  if ollama pull "$tag"; then
    echo "    ok: $tag"
  else
    echo "    FAILED: $tag" >&2
    FAILED=1
  fi
  echo
done

echo "Installed Ollama models (name + size):"
ollama list || true
echo
echo "Next steps:"
echo "  1. Start the server (if not already running):   ollama serve"
echo "  2. Point the red team at the local roster:"
echo "       from promptpolygraph.redteam.roster import load_roster, to_profile"
echo "       profile = to_profile(load_roster())"
echo "     or use the 'local_swarm' profile / config llm.provider: ollama."
echo
echo "See docs/REDTEAM_LOCAL.md for hardware tiers and details."

exit $FAILED
