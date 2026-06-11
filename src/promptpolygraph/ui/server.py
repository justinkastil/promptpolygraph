"""A local, read-only dashboard server for PromptPolygraph runs.

Pure Python stdlib (``http.server`` + ``socketserver``) — no FastAPI, no extra
deps. It opens the CLI's SQLite store read-only and exposes a tiny JSON API plus
a single-page UI so a user can browse and inspect evaluation runs the CLI has
produced. Nothing here writes to the store or mutates run artifacts.

Public entry point: :func:`serve_dashboard`.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .page import PAGE

# Report formats -> (filename, content-type).
_REPORT_FORMATS: dict[str, tuple[str, str]] = {
    "md": ("report.md", "text/markdown; charset=utf-8"),
    "html": ("report.html", "text/html; charset=utf-8"),
    "pdf": ("report.pdf", "application/pdf"),
    "docx": (
        "report.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}


def _summary_for_run(run_dir: Path, run: Any, store: Any) -> dict[str, Any]:
    """Return the run's summary: prefer the on-disk summary.json, else recompute.

    Older runs (or runs that skipped report rendering) may lack summary.json;
    in that case we recompute with the default rubric via ``analyze.summarize``.
    If a rubric path is configured on the run we try it, but a default is a fine
    fallback and never fatal.
    """
    sfile = run_dir / "summary.json"
    if sfile.is_file():
        try:
            return json.loads(sfile.read_text(encoding="utf-8"))
        except Exception:
            pass  # fall through to recompute

    # Recompute from the store.
    try:
        from promptpolygraph.analyze import default_rubric, load_rubric, summarize

        rubric = None
        cfg = getattr(run, "config", None) or {}
        rubric_path = None
        try:
            rubric_path = (cfg.get("analyze") or {}).get("rubric")
        except Exception:
            rubric_path = None
        if rubric_path:
            try:
                rubric = load_rubric(rubric_path)
            except Exception:
                rubric = None
        if rubric is None:
            rubric = default_rubric()

        run_id = run.run_id
        cases = store.get_cases(run_id)
        responses = store.get_responses(run_id)
        scores = store.get_scores(run_id)
        return summarize(cases, responses, scores, rubric)
    except Exception:
        return {}


class _Handler(BaseHTTPRequestHandler):
    # Injected by the server factory below.
    out_dir: Path = Path(".")
    store_path: Path = Path("polygraph.sqlite")

    server_version = "PromptPolygraphUI/1.0"
    protocol_version = "HTTP/1.1"

    # ---- low-level write helpers ----------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _not_found(self, msg: str = "not found") -> None:
        self._json({"error": msg}, status=HTTPStatus.NOT_FOUND)

    def _open_store(self) -> Any:
        from promptpolygraph.runner import SQLiteStore

        return SQLiteStore(str(self.store_path))

    # ---- routing --------------------------------------------------------
    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._route()
        except BrokenPipeError:
            pass
        except Exception as exc:  # never let one bad request kill the server
            try:
                self._json({"error": "internal error", "detail": str(exc)}, status=500)
            except Exception:
                pass

    def _route(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if not path.startswith("/api/"):
            self._not_found("unknown path")
            return

        parts = [p for p in path.split("/") if p]  # e.g. ["api","runs","<id>","cases"]

        if parts == ["api", "runs"]:
            self._api_runs()
            return

        if parts == ["api", "compare"]:
            self._api_compare(query)
            return

        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "runs":
            run_id = parts[2]
            tail = parts[3] if len(parts) > 3 else None
            if tail is None:
                self._api_run(run_id)
            elif tail == "cases":
                self._api_cases(run_id)
            elif tail == "audit":
                self._api_audit(run_id)
            elif tail == "report":
                self._api_report(run_id, query)
            else:
                self._not_found("unknown run sub-resource")
            return

        self._not_found("unknown path")

    # ---- API endpoints --------------------------------------------------
    def _api_runs(self) -> None:
        store = self._open_store()
        out: list[dict[str, Any]] = []
        for run in store.list_runs():
            run_dir = self.out_dir / run.run_id
            overall = None
            sfile = run_dir / "summary.json"
            if sfile.is_file():
                try:
                    overall = json.loads(sfile.read_text(encoding="utf-8")).get("overall_pass")
                except Exception:
                    overall = None
            out.append(
                {
                    "run_id": run.run_id,
                    "name": run.name,
                    "mode": run.mode,
                    "adapter": run.adapter,
                    "model": run.model,
                    "total_cases": run.total_cases,
                    "completed_cases": run.completed_cases,
                    "overall_pass": overall,
                    "created_at": run.created_at,
                    "completed_at": run.completed_at,
                }
            )
        self._json(out)

    def _api_run(self, run_id: str) -> None:
        store = self._open_store()
        run = store.get_run(run_id)
        if run is None:
            self._not_found("run not found")
            return
        run_dir = self.out_dir / run_id
        summary = _summary_for_run(run_dir, run, store)
        self._json({"run": run.model_dump(), "summary": summary})

    def _api_cases(self, run_id: str) -> None:
        store = self._open_store()
        run = store.get_run(run_id)
        if run is None:
            self._not_found("run not found")
            return
        responses = {r.case_id: r for r in store.get_responses(run_id)}
        scores = {s.case_id: s for s in store.get_scores(run_id)}
        out: list[dict[str, Any]] = []
        for case in store.get_cases(run_id):
            resp = responses.get(case.id)
            score = scores.get(case.id)
            out.append(
                {
                    "case": case.model_dump(),
                    "response": resp.model_dump() if resp is not None else None,
                    "score": score.model_dump() if score is not None else None,
                }
            )
        self._json(out)

    def _api_compare(self, query: dict[str, list[str]]) -> None:
        """Optional server-side comparison of N runs.

        Best-effort and fully guarded: the dashboard UI builds its own
        comparison client-side from ``/api/runs`` + ``/api/runs/{id}`` and never
        depends on this endpoint. If ``promptpolygraph.compare.compare_runs`` is
        importable we use it; otherwise we fall back to the package's pairwise
        A/B over the first two run ids. Any failure yields an empty payload so a
        caller can degrade gracefully.
        """
        raw = (query.get("runs", [""])[0] or "").strip()
        ids = [r.strip() for r in raw.split(",") if r.strip()]
        if len(ids) < 2:
            self._json({"error": "compare needs >= 2 run ids"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            import promptpolygraph.compare as _cmp

            store = self._open_store()
            # Prefer an N-run helper if the package exposes one.
            compare_runs = getattr(_cmp, "compare_runs", None)
            if callable(compare_runs):
                try:
                    self._json(compare_runs(ids, store=store))  # type: ignore[call-arg]
                    return
                except Exception:
                    pass  # fall through to pairwise
            # Fallback: pairwise A/B over the first two runs.
            a, b = ids[0], ids[1]
            cases = store.get_cases(a)
            scores_a = store.get_scores(a)
            scores_b = store.get_scores(b)
            result = _cmp.pairwise(cases, scores_a, scores_b, run_a=a, run_b=b)
            self._json(result)
        except Exception as exc:
            self._json({"error": "compare unavailable", "detail": str(exc)}, status=HTTPStatus.NOT_FOUND)

    def _api_audit(self, run_id: str) -> None:
        afile = self.out_dir / run_id / "audit.json"
        if not afile.is_file():
            self._json({}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            self._json(json.loads(afile.read_text(encoding="utf-8")))
        except Exception:
            self._json({}, status=HTTPStatus.NOT_FOUND)

    def _api_report(self, run_id: str, query: dict[str, list[str]]) -> None:
        fmt = (query.get("format", ["html"])[0] or "html").lower()
        spec = _REPORT_FORMATS.get(fmt)
        if spec is None:
            self._not_found("unknown report format")
            return
        filename, content_type = spec
        fpath = self.out_dir / run_id / filename
        if not fpath.is_file():
            self._not_found(f"no {fmt} report for this run")
            return
        try:
            data = fpath.read_bytes()
        except Exception:
            self._not_found("could not read report")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if fmt in ("pdf", "docx"):
            self.send_header(
                "Content-Disposition", f'attachment; filename="{run_id[:8]}-{filename}"'
            )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ---- quiet logging --------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # Keep the console clean; uncomment for debugging.
        return


def serve_dashboard(
    *,
    out_dir: str,
    store_path: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Serve the read-only PromptPolygraph dashboard until interrupted.

    Args:
        out_dir: directory the CLI wrote runs into (holds ``polygraph.sqlite``
            and one ``<run_id>/`` artifact dir per run).
        store_path: explicit path to the SQLite store; defaults to
            ``<out_dir>/polygraph.sqlite``.
        host: bind address (loopback by default — this is a local tool).
        port: bind port.
        open_browser: if True, open the default browser at the served URL.

    Blocks in ``serve_forever`` and returns cleanly on Ctrl-C.
    """
    out_path = Path(out_dir).expanduser().resolve()
    store = Path(store_path).expanduser().resolve() if store_path else out_path / "polygraph.sqlite"

    handler = type(
        "_BoundHandler",
        (_Handler,),
        {"out_dir": out_path, "store_path": store},
    )

    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise SystemExit(
            f"Could not bind {host}:{port} — {exc}. "
            f"Is another process using the port? Try a different --port."
        ) from exc

    url = f"http://{host}:{port}"
    print(f"PromptPolygraph dashboard serving {out_path}")
    print(f"  store: {store}")
    print(f"  open:  {url}   (Ctrl-C to stop)")
    if not store.is_file():
        print(f"  note:  store not found at {store} yet — runs will appear once the CLI writes there.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        httpd.shutdown()
        httpd.server_close()
