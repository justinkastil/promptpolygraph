# Local Red-Team Roster — Operator Guide

PromptPolygraph's red-team arena runs a roster of **attacker** agents that
generate adversarial probes against a system you own, plus a **judge** that
scores whether each exchange breached a guardrail. This guide covers running
that roster on **local open-weight models** so the whole loop runs offline, on
your own hardware, with no API key and no data leaving the machine.

> This is for **authorized red-teaming of a system you own** — surfacing
> vulnerabilities and the guardrails that fix them. The models below are
> mainstream open instruct models (Llama 3.x, Qwen2.5/3, Mistral); they are the
> mutation engine. The actual attack corpora come from separate OSS tooling.

---

## 1. The manifest: `redteam-models.yaml`

Your team owns `redteam-models.yaml` at the repo root. It is the single source
of truth for which models compose the roster. Each entry:

| field        | meaning                                                       |
|--------------|---------------------------------------------------------------|
| `name`       | a short unique label you choose                               |
| `role`       | `attacker` or `judge` (the first `judge` entry is used)        |
| `backend`    | `ollama`, `hf`, or `mlx`                                       |
| `ollama_tag` | the `ollama pull` tag (required for `backend: ollama`)        |
| `hf_repo`    | the HuggingFace repo id (required for `backend: hf` / `mlx`)  |
| `params`     | human-readable size, e.g. `"8B"`                              |
| `min_ram_gb` | unified memory / VRAM needed to run it comfortably            |
| `notes`      | anything useful to your team                                  |

Edit it freely — add models you've pulled, remove ones you don't want, change
the judge. Keep **attackers small and fast** and spend your memory budget on a
**strong judge**.

---

## 2. Hardware tiers

### Memory → model-size rule of thumb

This applies to GPU VRAM, or to **unified memory** on Apple Silicon / DGX Spark
(where CPU and GPU share one pool). Sizes assume 4-bit / Q4 quantization, which
is what Ollama and MLX ship by default.

| Memory (VRAM or unified) | Comfortable model size      | Example roster                          |
|--------------------------|-----------------------------|-----------------------------------------|
| 8 GB                     | 7–8B                        | attackers only (llama3.1:8b, qwen2.5:7b)|
| 16 GB                    | up to ~14B                  | attackers + 14B; small local judge      |
| 24 GB                    | up to ~30B                  | attackers + a 30B judge                 |
| 40 GB+                   | ~70B (quantized)            | full swarm + 70B judge                  |
| 128 GB unified           | 70B comfortably, room spare | multi-agent swarm **and** a 70B judge   |

### Mac Studio (Apple Silicon) — Ollama or MLX

The simplest path on macOS. Two equivalent options:

- **Ollama** (recommended to start). Install from <https://ollama.com/download>.
  It pulls quantized GGUF models and serves an HTTP API on `localhost:11434`.
  Use `backend: ollama` entries and `scripts/redteam_pull_ollama.sh`.
- **MLX** (Apple's native ML framework, often faster on Apple Silicon). Use
  `backend: mlx` entries pointing at `mlx-community/*` repos; fetch them with
  `scripts/redteam_pull_hf.py`, then serve with `mlx_lm.server` (exposes an
  OpenAI-compatible endpoint). A 64–128 GB Mac Studio can host a 70B judge plus
  several small attackers at once.

### NVIDIA DGX Spark — 128 GB unified, batteries included

The DGX Spark ships with **128 GB of unified memory** and a Grace-Blackwell GPU,
with **Ollama, Docker, and CUDA preinstalled**. It is an ideal single box for a
**multi-agent local swarm**: run several 7–14B attackers concurrently *and* a
70B judge, all in unified memory, fully offline.

- Out of the box: `ollama serve` is available; just run the pull script and go.
- For raw HF weights: use the preinstalled CUDA + Docker (e.g. a vLLM or TGI
  container) to serve `backend: hf` models over an OpenAI-compatible endpoint.
- The 128 GB pool means you rarely have to choose between swarm breadth and
  judge quality — run both.

### Cloud GPU

Rent an A100/H100 (or smaller L4/A10) instance. Install Ollama or run vLLM/TGI
in a container, expose the endpoint to the machine running PromptPolygraph
(SSH-tunnel or private network), and set `base_url` accordingly. A 24 GB cloud
GPU comfortably hosts a 30B judge; 40 GB+ hosts a 70B.

### Docker

The repo already ships a `Dockerfile` / `docker-compose.yml`. To run a fully
local stack, add an Ollama service (e.g. the official `ollama/ollama` image)
alongside PromptPolygraph, pull the roster into the Ollama volume, and set the
red-team `base_url` to the Ollama service hostname. On Linux with NVIDIA, pass
`--gpus all` (or the compose `deploy.resources.reservations.devices` GPU stanza)
so the container can see the GPU.

---

## 3. Pulling the models

After editing the manifest, pull everything it declares:

```sh
# Ollama models (backend: ollama):
sh scripts/redteam_pull_ollama.sh

# HuggingFace / MLX weights (backend: hf, backend: mlx):
python scripts/redteam_pull_hf.py             # download
python scripts/redteam_pull_hf.py --dry-run   # preview (lists models + min_ram)
```

Both scripts are safe + idempotent. The Ollama script re-pulls only changed
layers and prints installed sizes plus a reminder to start `ollama serve`. The
HF script lazily imports `huggingface_hub` — if it's not installed it prints
`pip install huggingface_hub` and exits cleanly (so `--dry-run` works with no
extra dependency). **Check each model's license** on its HuggingFace page before
downloading; gated repos require `huggingface-cli login`.

---

## 4. Pointing the red team at the local roster

### From the manifest (programmatic)

The roster module turns your manifest into a runnable profile:

```python
from promptpolygraph.redteam.roster import load_roster, to_profile
from promptpolygraph.redteam import run_redteam

roster = load_roster()                 # reads ./redteam-models.yaml
profile = to_profile(roster)           # a "local_swarm" profile, all-local
# profile.attackers -> Ollama/local-backed agents across the strategy families
# profile.judge_provider / judge_model -> your roster's judge entry
```

`to_profile` round-robins the strategy families across your declared attackers,
so every local attacker model gets used. If the manifest is missing, `load_roster`
falls back to a sensible default roster so the engine always has something to run.

### Via the built-in `local_swarm` profile

The engine also ships a `local_swarm` profile (all seven strategies on local
open models, local judge, 100% offline). Use it directly when you don't need a
custom roster.

### Via config

Set the LLM provider to Ollama in your config so the whole run stays local:

```yaml
llm:
  provider: ollama
  model: llama3.1:8b
  base_url: http://localhost:11434
```

---

## 5. Mixing in frontier models

The roster is local-first, but the engine's per-agent backends are pluggable.
You can mix a frontier model (e.g. Claude) in at the engine level — for example
to run the *clever multi-turn* strategies on a frontier model while local models
generate the high-volume raw probes, or to use a frontier model as the breach
judge. See the `mixed` and `pressure` built-in profiles for that pattern. The
local roster keeps you fully offline by default; reach for frontier models only
when you want extra adversarial sophistication and accept the network/API cost.
