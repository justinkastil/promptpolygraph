"""Local, CLI-first, read-only web dashboard for PromptPolygraph runs.

Stdlib-only (``http.server``). No FastAPI, no extra dependencies. The public
surface is :func:`serve_dashboard`, which the CLI wires to a command.
"""

from __future__ import annotations

from .arena import render_arena_page
from .server import serve_dashboard

__all__ = ["serve_dashboard", "render_arena_page"]
