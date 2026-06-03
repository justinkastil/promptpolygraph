"""Persona package: the bundled persona library + persona creation tools.

``library`` loads and selects from the bundled panel of distinct individuals
(package data YAML); ``new`` synthesizes fresh personas or whole panels from a
description or a product domain.
"""

from __future__ import annotations

from .library import load_library, load_personas_file, sample_pool, select
from .new import create_persona, generate_panel

__all__ = [
    "load_library",
    "sample_pool",
    "select",
    "load_personas_file",
    "create_persona",
    "generate_panel",
]
