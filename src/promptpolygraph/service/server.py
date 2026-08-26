"""Uvicorn entry point for the API service.

    polygraph-server
    POLYGRAPH_HOST=0.0.0.0 POLYGRAPH_PORT=8080 polygraph-server
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "promptpolygraph.service.app:app",
        host=os.environ.get("POLYGRAPH_HOST", "0.0.0.0"),
        port=int(os.environ.get("POLYGRAPH_PORT", "8080")),
        workers=int(os.environ.get("POLYGRAPH_WEB_WORKERS", "1")),
        log_level=os.environ.get("POLYGRAPH_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
