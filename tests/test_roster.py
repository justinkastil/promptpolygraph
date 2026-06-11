"""Tests for the controllable local-model roster.

Covers: parsing the shipped ``redteam-models.yaml``, building a runnable
``RedTeamProfile`` from a roster (ollama-backed attackers + a judge), and the
missing-file fallback. All offline; no models are pulled or called.
"""

from __future__ import annotations

from pathlib import Path

from promptpolygraph.redteam.models import RedTeamProfile
from promptpolygraph.redteam.roster import (
    ModelEntry,
    attackers,
    default_roster,
    judge,
    load_roster,
    to_profile,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "redteam-models.yaml"


def test_shipped_manifest_parses():
    roster = load_roster(MANIFEST)
    assert isinstance(roster, list) and roster
    assert all(isinstance(e, ModelEntry) for e in roster)

    atk = attackers(roster)
    assert atk, "shipped manifest should declare attackers"
    j = judge(roster)
    assert j is not None and j.role == "judge"

    # The curated defaults are Ollama-backed and carry memory guidance.
    assert any(e.backend == "ollama" for e in atk)
    assert all(e.min_ram_gb > 0 for e in roster)
    # ollama attackers expose a usable model id (the pull tag).
    ollama_atk = [e for e in atk if e.backend == "ollama"]
    assert all(":" in e.model_id for e in ollama_atk)


def test_to_profile_yields_runnable_profile():
    roster = load_roster(MANIFEST)
    profile = to_profile(roster)

    assert isinstance(profile, RedTeamProfile)
    assert profile.name == "local_swarm"
    assert profile.attackers, "profile should have attacker agents"

    # Ollama-backed attackers map to provider "ollama".
    providers = {a.provider for a in profile.attackers}
    assert "ollama" in providers

    # Every strategy family is covered (round-robin over 7 strategies).
    strategies = {a.strategy for a in profile.attackers}
    assert "jailbreak" in strategies
    assert len(strategies) == 7

    # The judge came from the roster's judge entry.
    j = judge(roster)
    assert profile.judge_provider == j.provider
    assert profile.judge_model == j.model_id


def test_to_profile_custom_args():
    roster = load_roster(MANIFEST)
    profile = to_profile(
        roster, name="my_swarm", strategies=["jailbreak", "prompt_injection"], turns=3
    )
    assert profile.name == "my_swarm"
    assert profile.turns == 3
    assert {a.strategy for a in profile.attackers} == {"jailbreak", "prompt_injection"}


def test_missing_file_fallback():
    roster = load_roster("/nonexistent/redteam-models.yaml")
    assert roster, "missing manifest should fall back to a default roster"
    assert roster == default_roster()

    # The fallback is itself usable.
    profile = to_profile(roster)
    assert isinstance(profile, RedTeamProfile)
    assert profile.attackers
    assert profile.judge_provider == "ollama"


def test_default_roster_returns_copies():
    a = default_roster()
    b = default_roster()
    a[0].name = "mutated"
    assert b[0].name != "mutated", "default_roster must return independent copies"
