"""Controllable local-model roster for the red-team arena.

Teams own which open-weight models compose the attacker / judge roster by
editing ``redteam-models.yaml`` at the repo root. This module turns that
manifest into a runnable :class:`~promptpolygraph.redteam.RedTeamProfile` whose
attackers run on the local models you've pulled (Ollama / HF / MLX) and whose
breach judge is the roster's judge entry.

This is for **authorized red-teaming of a system you own**. The models named
here are mainstream open instruct models — the mutation engine — and the actual
attack corpora come from separate OSS tooling.

Typical use::

    from promptpolygraph.redteam.roster import load_roster, to_profile
    profile = to_profile(load_roster())   # 100%-local "local_swarm" profile

The loader is robust to a missing / unreadable manifest: it falls back to a
sensible built-in roster so the engine always has something runnable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .models import Attacker, RedTeamProfile

# Strategy families the engine knows about (kept in sync with strategies.py).
_ALL_STRATEGIES = [
    "jailbreak",
    "prompt_injection",
    "system_prompt_leak",
    "pii_extraction",
    "tool_abuse",
    "obfuscation",
    "refusal_robustness",
]

DEFAULT_MANIFEST = "redteam-models.yaml"

Role = Literal["attacker", "judge"]
Backend = Literal["ollama", "hf", "mlx"]

# How a manifest backend maps to an engine provider. `hf` / `mlx` weights are
# served locally through an OpenAI-compatible endpoint (vLLM / TGI / LM Studio /
# mlx_lm.server), so they ride the "openai" provider with a local base_url.
_BACKEND_TO_PROVIDER: dict[str, str] = {
    "ollama": "ollama",
    "hf": "openai",
    "mlx": "openai",
}


class ModelEntry(BaseModel):
    """One model declared in the roster manifest."""

    name: str
    role: Role = "attacker"
    backend: Backend = "ollama"
    ollama_tag: Optional[str] = None
    hf_repo: Optional[str] = None
    params: str = ""
    min_ram_gb: float = 0.0
    notes: str = ""
    base_url: Optional[str] = None
    org: str = ""          # publisher, e.g. Meta / Google / NVIDIA / Mistral AI
    provenance: str = ""   # jurisdiction, e.g. "US", "EU" — matters for security/regulated use
    license: str = ""      # model license

    @property
    def model_id(self) -> str:
        """The model identifier the engine should send to the backend."""
        if self.backend == "ollama":
            return self.ollama_tag or self.name
        return self.hf_repo or self.name

    @property
    def provider(self) -> str:
        return _BACKEND_TO_PROVIDER.get(self.backend, "ollama")


# A safe fallback roster used when the manifest is missing / unparseable.
# Defaults are widely-used open models with their publisher + jurisdiction
# labeled (org / provenance), so teams can vet provenance for their compliance
# needs. Any other model is equally usable — just add it to the manifest.
_DEFAULT_ENTRIES: list[ModelEntry] = [
    ModelEntry(
        name="gemma3-4b", role="attacker", backend="ollama",
        ollama_tag="gemma3:4b", params="4B", min_ram_gb=8,
        org="Google", provenance="US", license="Gemma",
        notes="Small, fast attacker (Gemma 3 4B).",
    ),
    ModelEntry(
        name="llama31-8b", role="attacker", backend="ollama",
        ollama_tag="llama3.1:8b", params="8B", min_ram_gb=8,
        org="Meta", provenance="US", license="Llama 3.1 Community",
        notes="English-first default attacker (Llama 3.1 8B).",
    ),
    ModelEntry(
        name="mistral-nemo-12b", role="attacker", backend="ollama",
        ollama_tag="mistral-nemo:12b", params="12B", min_ram_gb=16,
        org="Mistral AI", provenance="EU", license="Apache-2.0",
        notes="EU-provenance attacker (Mistral Nemo 12B).",
    ),
    ModelEntry(
        name="phi4-14b", role="attacker", backend="ollama",
        ollama_tag="phi4:14b", params="14B", min_ram_gb=16,
        org="Microsoft", provenance="US", license="MIT",
        notes="Reasoning-leaning attacker for multi-turn (Phi-4 14B).",
    ),
    ModelEntry(
        name="llama33-70b", role="judge", backend="ollama",
        ollama_tag="llama3.3:70b", params="70B", min_ram_gb=48,
        org="Meta", provenance="US", license="Llama 3.3 Community",
        notes="Breach judge (Llama 3.3 70B, quantized). Nemotron 3 Super is a strong "
              "NVIDIA-stack alternative on DGX Spark.",
    ),
]


def default_roster() -> list[ModelEntry]:
    """A sensible built-in roster (deep copies, safe to mutate)."""
    return [e.model_copy(deep=True) for e in _DEFAULT_ENTRIES]


def load_roster(path: str | Path = DEFAULT_MANIFEST) -> list[ModelEntry]:
    """Load and validate the model roster from a YAML manifest.

    Returns a list of :class:`ModelEntry`. If the file is missing, empty, or
    unparseable — or yields no valid entries — a sensible default roster is
    returned instead so the engine always has something to run.
    """
    p = Path(path)
    if not p.is_file():
        return default_roster()

    try:
        import yaml  # PyYAML ships with the project deps.

        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return default_roster()

    items = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return default_roster()

    entries: list[ModelEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            entries.append(ModelEntry(**item))
        except Exception:
            # Skip malformed entries rather than failing the whole load.
            continue

    return entries or default_roster()


def attackers(roster: list[ModelEntry]) -> list[ModelEntry]:
    """The attacker entries from a roster."""
    return [e for e in roster if e.role == "attacker"]


def judge(roster: list[ModelEntry]) -> ModelEntry | None:
    """The judge entry (first one declared), or ``None`` if none is set."""
    for e in roster:
        if e.role == "judge":
            return e
    return None


def to_profile(
    roster: list[ModelEntry] | None = None,
    *,
    name: str = "local_swarm",
    strategies: list[str] | None = None,
    turns: int = 1,
) -> RedTeamProfile:
    """Build a runnable :class:`RedTeamProfile` from a roster.

    Each strategy family is assigned to the roster's attacker models in a
    round-robin, so every declared local attacker gets used. The judge entry
    becomes the profile's breach judge. With no judge declared, the engine's
    default judge provider is left in place.
    """
    if roster is None:
        roster = load_roster()

    strats = strategies if strategies is not None else list(_ALL_STRATEGIES)
    atk_entries = attackers(roster)

    agents: list[Attacker] = []
    if atk_entries:
        for i, strategy in enumerate(strats):
            entry = atk_entries[i % len(atk_entries)]
            agents.append(
                Attacker(
                    strategy=strategy,
                    provider=entry.provider,
                    model=entry.model_id,
                    base_url=entry.base_url,
                )
            )

    j = judge(roster)
    judge_kwargs: dict = {}
    if j is not None:
        judge_kwargs = {
            "judge_provider": j.provider,
            "judge_model": j.model_id,
            "judge_base_url": j.base_url,
        }

    attacker_names = ", ".join(sorted({e.name for e in atk_entries})) or "none"
    judge_name = j.name if j else "engine default"
    return RedTeamProfile(
        name=name,
        description=(
            "Local roster red team — attackers: "
            f"{attacker_names}; judge: {judge_name}. Runs offline on pulled "
            "open-weight models."
        ),
        attackers=agents,
        turns=turns,
        **judge_kwargs,
    )
