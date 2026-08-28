"""Small stdlib-only JSON logging and trace correlation helpers."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

trace_id_var: ContextVar[str | None] = ContextVar("service_trace_id", default=None)
span_id_var: ContextVar[str | None] = ContextVar("service_span_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = trace_id_var.get()
        span_id = span_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id
        if span_id:
            payload["span_id"] = span_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_polygraph_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._polygraph_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def inbound_trace(traceparent: str | None) -> tuple[str | None, str | None]:
    """Extract W3C trace/span identifiers without accepting arbitrary log text."""
    if traceparent:
        parts = traceparent.split("-")
        if (len(parts) == 4 and len(parts[1]) == 32 and len(parts[2]) == 16
                and all(ch in "0123456789abcdefABCDEF" for ch in parts[1] + parts[2])):
            return parts[1].lower(), parts[2].lower()
    try:
        from opentelemetry import trace  # optional integration
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            return f"{context.trace_id:032x}", f"{context.span_id:016x}"
    except (ImportError, AttributeError):
        pass
    return None, None
