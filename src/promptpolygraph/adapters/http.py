"""Generic HTTP/REST adapter for any web endpoint.

Configurable so it fits most JSON APIs without code:
  - method, url, headers (env-var interpolation via ${VAR})
  - body_template: a JSON-able dict; the string "{{prompt}}" anywhere inside
    is replaced with the case prompt (also "{{category}}", "{{id}}")
  - response_path: a JMESPath expression extracting the answer text from the
    JSON response (default "text"); falls back to the raw body if it misses
  - tokens_in_path / tokens_out_path / model_path: optional JMESPath for usage
"""

from __future__ import annotations

import base64
import copy
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
import jmespath

from ..models import Attachment, Case, Response
from .base import BaseAdapter

_ENV = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _interp_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _interp_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interp_env(v) for v in value]
    return value


def _fill(value: Any, case: Case) -> Any:
    if isinstance(value, str):
        return (
            value.replace("{{prompt}}", case.prompt)
            .replace("{{category}}", case.category)
            .replace("{{id}}", case.id)
        )
    if isinstance(value, dict):
        return {k: _fill(v, case) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, case) for v in value]
    return value


class HTTPAdapter(BaseAdapter):
    name = "http"

    def __init__(
        self,
        name: str | None = None,
        *,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        body_template: dict[str, Any] | None = None,
        response_path: str = "text",
        tokens_in_path: str | None = None,
        tokens_out_path: str | None = None,
        model_path: str | None = None,
        cost_path: str | None = None,
        body_mode: str = "json",
        prompt_field: str = "prompt",
        file_field: str = "file",
        timeout: float = 60.0,
        **_: Any,
    ):
        super().__init__(name)
        self._url = _interp_env(url)
        self._method = method.upper()
        self._headers = _interp_env(headers or {})
        self._body_template = body_template or {"prompt": "{{prompt}}"}
        # "json" (default) or "multipart". multipart is selected automatically
        # for a case that carries attachments; this option forces it always.
        self._body_mode = body_mode
        self._prompt_field = prompt_field  # form field holding the prompt text
        self._file_field = file_field      # form field holding an attachment
        self._response_path = response_path
        self._tokens_in_path = tokens_in_path
        self._tokens_out_path = tokens_out_path
        self._model_path = model_path
        self._cost_path = cost_path
        self._client = httpx.AsyncClient(timeout=timeout)

    def _multipart(self, case: Case) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build (data, files) for an httpx multipart request. Text fields from
        the filled body template ride in `data`; each attachment becomes a file
        part. The bare text path is never routed here, so it stays byte-identical.
        """
        body = _fill(copy.deepcopy(self._body_template), case)
        data: dict[str, Any] = {}
        if isinstance(body, dict):
            data = {k: v for k, v in body.items() if isinstance(v, (str, int, float, bool))}
        data.setdefault(self._prompt_field, case.prompt)
        files: dict[str, Any] = {}
        for i, att in enumerate(case.attachments):
            field = self._file_field if len(case.attachments) == 1 else f"{self._file_field}{i}"
            files[field] = _file_part(att)
        return data, files

    async def query(self, case: Case) -> Response:
        start = time.perf_counter()
        use_multipart = self._body_mode == "multipart" or case.has_attachments()
        try:
            if use_multipart:
                data, files = self._multipart(case)
                resp = await self._client.request(
                    self._method, self._url, headers=self._headers,
                    data=data, files=files or None,
                )
            else:
                body = _fill(copy.deepcopy(self._body_template), case)
                resp = await self._client.request(
                    self._method, self._url, headers=self._headers, json=body
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return Response(
                case_id=case.id,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=self._elapsed_ms(start),
                source=self.name,
            )
        text = jmespath.search(self._response_path, data)
        if text is None:
            text = data if isinstance(data, str) else str(data)
        return Response(
            case_id=case.id,
            text=str(text),
            latency_ms=self._elapsed_ms(start),
            tokens_in=_search_int(self._tokens_in_path, data),
            tokens_out=_search_int(self._tokens_out_path, data),
            cost_usd=_search_float(self._cost_path, data),
            model=_search_str(self._model_path, data),
            source=self.name,
            raw=data if isinstance(data, dict) else {"body": data},
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _file_part(att: Attachment) -> tuple[str, bytes, str]:
    """An httpx file tuple (filename, bytes, content_type) for one attachment.

    Resolves bytes from data_b64, then a local path; a url-only attachment is not
    fetched (no network in the request build) and is sent as a zero-byte part
    carrying its url in the filename so the receiving service can resolve it.
    """
    media_type = att.media_type or (
        mimetypes.guess_type(att.path or att.name or "")[0] or "application/octet-stream"
    )
    if att.data_b64:
        return (att.name or "attachment", base64.b64decode(att.data_b64), media_type)
    if att.path:
        p = Path(att.path)
        return (att.name or p.name, p.read_bytes(), media_type)
    if att.url:
        return (att.name or att.url, b"", media_type)
    return (att.name or "attachment", b"", media_type)


def _search_int(path: str | None, data: Any) -> int | None:
    if not path:
        return None
    v = jmespath.search(path, data)
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _search_str(path: str | None, data: Any) -> str | None:
    if not path:
        return None
    v = jmespath.search(path, data)
    return str(v) if v is not None else None


def _search_float(path: str | None, data: Any) -> float | None:
    if not path:
        return None
    v = jmespath.search(path, data)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
