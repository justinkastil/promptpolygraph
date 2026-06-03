"""Corpus module — load fixed probe sets or synthesize new ones.

`load_corpus` reads a directory (or single file) of category-keyed JSON probe
files into `Case` objects. `generate` is the async LLM-backed (or mock)
primitive that synthesizes new prompts. `build_corpus` is the synchronous
dispatcher the CLI calls to turn a `CorpusConfig` into a list of `Case`s,
selecting fixed / varied / adversarial / hybrid behavior.
"""

from __future__ import annotations

from .generator import build_corpus, generate
from .loader import load_corpus

__all__ = ["load_corpus", "build_corpus", "generate"]
