"""Uvicorn entry point for the API service.

    polygraph-server
    POLYGRAPH_HOST=0.0.0.0 POLYGRAPH_PORT=8080 polygraph-server
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    if "--validate-config" in sys.argv[1:]:
        from .startup_validate import run

        ok, report = run()
        for item in report:
            print(f"{item['status'].upper():4} {item['check']}: {item['detail']}")
        raise SystemExit(0 if ok else 1)

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
