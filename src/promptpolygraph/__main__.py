"""Enable `python -m promptpolygraph` as an alias for the `polygraph` CLI."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
