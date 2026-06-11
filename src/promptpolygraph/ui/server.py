"""A local, read-only dashboard server for PromptPolygraph runs.

Pure Python stdlib (``http.server`` + ``socketserver``) — no FastAPI, no extra
deps. It opens the CLI's SQLite store read-only and exposes a tiny JSON API plus
a single-page UI so a user can browse and inspect evaluation runs the CLI has
produced. Nothing here writes to the store or mutates run artifacts.

Public entry point: :func:`serve_dashboard`.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from .arena import render_arena_page
from .page import PAGE

# ── Control-plane state ─────────────────────────────────────────────────────
# Module-level progress map for in-process runs launched from the dashboard.
# Keyed by run_id -> {"stage", "completed?", "total?", "error?", ...}. A
# background daemon thread mutates this; handlers only read it. Plain dict
# writes are atomic enough under CPython's GIL for this single-key-per-run use.
PROGRESS: dict[str, dict[str, Any]] = {}


def _slugify(text: str, *, fallback: str = "panel") -> str:
    """A filesystem-safe snake_case slug for persona file names."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    slug = "_".join(words[:6]) if words else ""
    return slug or fallback


def _repo_root() -> Path:
    """The installed package's repo root (holds ``examples/``), best-effort."""
    import promptpolygraph

    return Path(promptpolygraph.__file__).resolve().parents[2]


def _want_mock(requested: bool | None) -> bool:
    """Mock when explicitly requested OR when no API key is configured."""
    if requested:
        return True
    return not os.environ.get("ANTHROPIC_API_KEY")

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

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._route_post()
        except BrokenPipeError:
            pass
        except Exception as exc:  # never let one bad request kill the server
            try:
                self._json({"error": "internal error", "detail": str(exc)}, status=500)
            except Exception:
                pass

    def _read_body(self) -> dict[str, Any]:
        """Parse the JSON request body; tolerate empty/garbage as ``{}``."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _route(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/redteam":
            self._redteam_page(query)
            return

        if path == "/api/redteam/stream":
            self._api_redteam_stream(query)
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

        if parts == ["api", "configs"]:
            self._api_configs()
            return

        if parts == ["api", "personas"]:
            self._api_personas()
            return

        if parts == ["api", "personas", "files", "download"]:
            self._api_persona_download(query)
            return

        if parts == ["api", "personas", "files"]:
            self._api_persona_files()
            return

        if parts == ["api", "providers"]:
            self._api_providers()
            return

        if parts == ["api", "corpus", "export"]:
            self._api_corpus_dir_export(query)
            return

        if parts == ["api", "corpus", "generate", "stream"]:
            self._api_corpus_generate_stream(query)
            return

        if parts == ["api", "redteam", "runs"]:
            self._api_redteam_runs()
            return

        if len(parts) >= 4 and parts[:3] == ["api", "redteam", "runs"]:
            rid = parts[3]
            tail = parts[4] if len(parts) > 4 else None
            if tail is None:
                self._api_redteam_run(rid)
            elif tail == "events":
                self._api_redteam_events(rid)
            else:
                self._not_found("unknown redteam sub-resource")
            return

        if len(parts) == 4 and parts[:2] == ["api", "run"] and parts[3] == "status":
            self._api_run_status(parts[2])
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
            elif tail == "corpus":
                self._api_corpus_export(run_id, query)
            else:
                self._not_found("unknown run sub-resource")
            return

        self._not_found("unknown path")

    def _route_post(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        parts = [p for p in path.split("/") if p]

        if parts == ["api", "run"]:
            self._api_run_launch()
            return
        if parts == ["api", "personas", "new"]:
            self._api_persona_new()
            return
        if parts == ["api", "personas", "generate"]:
            self._api_persona_generate()
            return
        if parts == ["api", "corpus", "generate"]:
            self._api_corpus_generate()
            return
        if parts == ["api", "redteam", "trace"]:
            self._api_redteam_trace()
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

    def _send_download(self, data: bytes, filename: str, content_type: str) -> None:
        """Serve raw bytes as a browser download (attachment)."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _api_corpus_export(self, run_id: str, query: dict[str, list[str]]) -> None:
        """Download a run's prompt corpus as json | jsonl | csv (the UI face of
        ``polygraph export``). ``prompts_only=1`` trims to prompt+category."""
        import csv
        import io

        store = self._open_store()
        run = store.get_run(run_id)
        if run is None:
            self._not_found("run not found")
            return
        cases = store.get_cases(run_id)
        fmt = (query.get("format", ["json"])[0] or "json").lower()
        prompts_only = (query.get("prompts_only", ["0"])[0] or "0").lower() in ("1", "true", "yes")

        if prompts_only:
            rows: list[Any] = [{"prompt": c.prompt, "category": c.category} for c in cases]
        else:
            rows = [c.model_dump(mode="json", exclude={"id"}) for c in cases]

        if fmt == "json":
            data = json.dumps(rows, indent=2, ensure_ascii=False).encode("utf-8")
            ctype = "application/json"
        elif fmt == "jsonl":
            data = ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")
            ctype = "application/x-ndjson"
        elif fmt == "csv":
            buf = io.StringIO()
            cols = ["prompt", "category", "subcategory", "expected_shape", "expected_behavior"]
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for c in cases:
                w.writerow({"prompt": c.prompt, "category": c.category,
                            "subcategory": getattr(c, "subcategory", None) or "",
                            "expected_shape": getattr(c, "expected_shape", None) or "",
                            "expected_behavior": getattr(c, "expected_behavior", None) or ""})
            data = buf.getvalue().encode("utf-8")
            ctype = "text/csv"
        else:
            self._not_found("unknown corpus format")
            return
        self._send_download(data, f"{run_id[:8]}-corpus.{fmt}", ctype)

    # ---- control plane: configs ----------------------------------------
    def _api_configs(self) -> None:
        """List selectable configs: bundled ``examples/*/config.yaml`` plus any
        ``*.yaml`` in a ``configs/`` dir under cwd or out_dir."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        def add(name: str, p: Path) -> None:
            rp = str(p.resolve())
            if rp in seen or not p.is_file():
                return
            seen.add(rp)
            out.append({"name": name, "path": rp})

        try:
            examples = _repo_root() / "examples"
            if examples.is_dir():
                for d in sorted(examples.iterdir()):
                    cfg = d / "config.yaml"
                    if cfg.is_file():
                        add(d.name, cfg)
        except Exception:
            pass

        for base in (Path.cwd(), self.out_dir):
            try:
                cdir = base / "configs"
                if cdir.is_dir():
                    for y in sorted(cdir.glob("*.yaml")):
                        add(y.stem, y)
                    for y in sorted(cdir.glob("*.yml")):
                        add(y.stem, y)
            except Exception:
                pass

        self._json(out)

    # ---- control plane: launch + status --------------------------------
    def _resolve_config_path(self, body: dict[str, Any]) -> str | None:
        """Map a config_path or config_name from the request to a file path."""
        cp = (body.get("config_path") or "").strip()
        if cp:
            p = Path(cp).expanduser()
            if p.is_file():
                return str(p.resolve())
            return None
        name = (body.get("config_name") or "").strip()
        if not name:
            return None
        # Match against the configs the /api/configs endpoint would list.
        try:
            examples = _repo_root() / "examples"
            cand = examples / name / "config.yaml"
            if cand.is_file():
                return str(cand.resolve())
        except Exception:
            pass
        for base in (Path.cwd(), self.out_dir):
            for ext in ("yaml", "yml"):
                cand = base / "configs" / f"{name}.{ext}"
                if cand.is_file():
                    return str(cand.resolve())
        return None

    def _api_run_launch(self) -> None:
        from promptpolygraph.config import Config
        from promptpolygraph.models import new_id
        from promptpolygraph.pipeline import run_pipeline
        from promptpolygraph.runner import SQLiteStore

        body = self._read_body()
        cfg_path = self._resolve_config_path(body)
        try:
            cfg = Config.load(cfg_path) if cfg_path else Config()
        except Exception as exc:
            self._json({"error": "could not load config", "detail": str(exc)},
                       status=HTTPStatus.BAD_REQUEST)
            return

        ov = body.get("overrides") or {}
        if not isinstance(ov, dict):
            ov = {}
        try:
            self._apply_overrides(cfg, ov)
        except Exception as exc:
            self._json({"error": "bad overrides", "detail": str(exc)},
                       status=HTTPStatus.BAD_REQUEST)
            return

        personas_path = (body.get("personas_path") or "").strip()
        if personas_path:
            cfg.personas_path = personas_path

        # The dashboard's store IS the run's store — write into out_dir.
        cfg.out_dir = str(self.out_dir)
        run_id = new_id()
        PROGRESS[run_id] = {"stage": "queued"}
        store_path = str(self.store_path)
        out_dir = str(self.out_dir)

        def _progress(stage: str, info: dict) -> None:
            PROGRESS[run_id] = {"stage": stage, **(info or {})}

        def _worker() -> None:
            try:
                store = SQLiteStore(store_path)
                asyncio.run(
                    run_pipeline(cfg, store, run_id=run_id, out_dir=out_dir, progress=_progress)
                )
                cur = PROGRESS.get(run_id) or {}
                if cur.get("stage") != "done":
                    PROGRESS[run_id] = {**cur, "stage": "done"}
            except Exception as exc:  # record, never crash the server
                PROGRESS[run_id] = {"stage": "error", "error": str(exc)}

        threading.Thread(target=_worker, daemon=True).start()
        self._json({"run_id": run_id, "status": "running"})

    @staticmethod
    def _apply_overrides(cfg: Any, ov: dict[str, Any]) -> None:
        """Apply UI dials onto a Config, ignoring blanks. Mutates ``cfg``."""
        def _int(v: Any) -> int | None:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        if ov.get("mode"):
            cfg.corpus.mode = str(ov["mode"])
        if ov.get("count") not in (None, ""):
            n = _int(ov.get("count"))
            if n is not None:
                cfg.corpus.count = n
        if ov.get("per_category") not in (None, ""):
            n = _int(ov.get("per_category"))
            if n is not None:
                cfg.corpus.per_category = n
        cats = ov.get("categories")
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(",") if c.strip()]
        if isinstance(cats, list) and cats:
            cfg.corpus.categories = [str(c) for c in cats]
        if ov.get("difficulty"):
            cfg.corpus.difficulty = str(ov["difficulty"])
        if ov.get("path"):
            cfg.corpus.path = str(ov["path"])
            if not ov.get("mode"):
                cfg.corpus.mode = "fixed"  # a saved corpus dir is loaded, not regenerated
        if "mock" in ov:
            cfg.mock = bool(ov["mock"])
        # Always run offline when no API key is configured.
        if _want_mock(cfg.mock):
            cfg.mock = True
        fmts = ov.get("formats")
        if isinstance(fmts, str):
            fmts = [f.strip() for f in fmts.split(",") if f.strip()]
        if isinstance(fmts, list) and fmts:
            cfg.report.formats = [str(f) for f in fmts]

    def _api_run_status(self, run_id: str) -> None:
        prog = dict(PROGRESS.get(run_id) or {})
        completed: int | None = prog.get("completed")
        total: int | None = prog.get("total")
        completed_at = None
        # Merge with the store row when present.
        try:
            store = self._open_store()
            run = store.get_run(run_id)
            if run is not None:
                if total is None:
                    total = run.total_cases
                if completed is None and run.completed_cases:
                    completed = run.completed_cases
                completed_at = run.completed_at
        except Exception:
            run = None

        stage = prog.get("stage") or ("queued" if run_id in PROGRESS else "unknown")
        error = prog.get("error")
        done = stage == "done" or (error is None and completed_at is not None and stage != "error")
        if error:
            done = True
        out = {
            "run_id": run_id,
            "stage": stage,
            "completed": completed,
            "total": total,
            "done": bool(done),
            "completed_at": completed_at,
        }
        if error:
            out["error"] = error
        self._json(out)

    # ---- control plane: persona studio ---------------------------------
    def _personas_dir(self) -> Path:
        d = self.out_dir / "personas"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _api_personas(self) -> None:
        from promptpolygraph import persona as P

        try:
            lib = P.load_library()
        except Exception as exc:
            self._json({"error": "could not load library", "detail": str(exc)},
                       status=HTTPStatus.NOT_FOUND)
            return
        self._json([p.model_dump() for p in lib])

    def _api_persona_files(self) -> None:
        """List saved persona yaml files under ``<out_dir>/personas/`` plus the
        bundled ``examples/*/personas.yaml``."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        def add(name: str, p: Path) -> None:
            rp = str(p.resolve())
            if rp in seen or not p.is_file():
                return
            seen.add(rp)
            out.append({"name": name, "path": rp})

        try:
            pd = self.out_dir / "personas"
            if pd.is_dir():
                for y in sorted(pd.glob("*.yaml")):
                    add(y.stem, y)
                for y in sorted(pd.glob("*.yml")):
                    add(y.stem, y)
        except Exception:
            pass
        try:
            examples = _repo_root() / "examples"
            if examples.is_dir():
                for d in sorted(examples.iterdir()):
                    pf = d / "personas.yaml"
                    if pf.is_file():
                        add(f"{d.name} (example)", pf)
        except Exception:
            pass
        self._json(out)

    def _persona_files_allowed(self) -> set[str]:
        """Resolved paths of persona files the UI is allowed to serve — the saved
        studio files plus the bundled example panels. Bounds the download endpoint
        so it can't be used to read arbitrary files."""
        allowed: set[str] = set()
        try:
            pd = self.out_dir / "personas"
            if pd.is_dir():
                for y in list(pd.glob("*.yaml")) + list(pd.glob("*.yml")):
                    allowed.add(str(y.resolve()))
        except Exception:
            pass
        try:
            examples = _repo_root() / "examples"
            if examples.is_dir():
                for d in examples.iterdir():
                    pf = d / "personas.yaml"
                    if pf.is_file():
                        allowed.add(str(pf.resolve()))
        except Exception:
            pass
        return allowed

    def _api_persona_download(self, query: dict[str, list[str]]) -> None:
        """Download a saved persona panel as YAML. Only files listed by
        ``/api/personas/files`` are servable."""
        want = (query.get("path", [""])[0] or "").strip()
        if not want:
            self._not_found("path required")
            return
        rp = str(Path(want).expanduser().resolve())
        if rp not in self._persona_files_allowed():
            self._not_found("persona file not found")
            return
        try:
            data = Path(rp).read_bytes()
        except Exception:
            self._not_found("could not read persona file")
            return
        self._send_download(data, Path(rp).name, "application/x-yaml")

    def _save_personas_yaml(self, path: Path, personas: list[Any]) -> None:
        import yaml

        data = {"personas": [p.model_dump() for p in personas]}
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _api_persona_new(self) -> None:
        from promptpolygraph import persona as P

        body = self._read_body()
        desc = str(body.get("description") or "").strip()
        if not desc:
            self._json({"error": "description required"}, status=HTTPStatus.BAD_REQUEST)
            return
        mock = _want_mock(bool(body.get("mock")))
        client = None
        if not mock:
            try:
                from promptpolygraph.llm import make_client

                client = make_client(None)
            except Exception:
                client = None
                mock = True
        try:
            persona = asyncio.run(P.create_persona(client, desc, mock=mock))
        except Exception as exc:
            self._json({"error": "create failed", "detail": str(exc)}, status=500)
            return

        slug = _slugify(getattr(persona, "id", "") or desc, fallback="persona")
        path = self._personas_dir() / f"{slug}.yaml"
        try:
            self._save_personas_yaml(path, [persona])
        except Exception:
            pass
        self._json({"persona": persona.model_dump(), "path": str(path)})

    def _api_persona_generate(self) -> None:
        from promptpolygraph import persona as P

        body = self._read_body()
        try:
            count = int(body.get("count") or 6)
        except (TypeError, ValueError):
            count = 6
        count = max(1, min(count, 24))
        domain = str(body.get("domain") or "general assistant").strip() or "general assistant"
        mock = _want_mock(bool(body.get("mock")))
        client = None
        if not mock:
            try:
                from promptpolygraph.llm import make_client

                client = make_client(None)
            except Exception:
                client = None
                mock = True
        try:
            panel = asyncio.run(P.generate_panel(client, count, domain, mock=mock))
        except Exception as exc:
            self._json({"error": "generate failed", "detail": str(exc)}, status=500)
            return

        slug = _slugify(domain, fallback="panel")
        path = self._personas_dir() / f"{slug}.yaml"
        try:
            self._save_personas_yaml(path, panel)
        except Exception:
            pass
        self._json({"panel": [p.model_dump() for p in panel], "path": str(path)})

    # ---- red-team arena -------------------------------------------------
    def _redteam_page(self, query: dict[str, list[str]]) -> None:
        """Serve the Arena page, wiring its SSE URL to the requested run.

        Any ``profile`` / ``config_name`` / ``config_path`` / ``mock`` query
        params are passed straight through to the stream URL so the page opens
        the right stream.
        """
        passthrough: list[tuple[str, str]] = []
        for key in ("profile", "config_name", "config_path", "mock"):
            vals = query.get(key)
            if vals and vals[0] != "":
                passthrough.append((key, vals[0]))
        qs = ("?" + urlencode(passthrough)) if passthrough else ""
        stream_url = "/api/redteam/stream" + qs
        try:
            html = render_arena_page(stream_url=stream_url, transport="sse")
        except Exception as exc:  # never 500 the page on a render glitch
            self._json({"error": "could not render arena", "detail": str(exc)}, status=500)
            return
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _redteam_target(self, query: dict[str, list[str]]) -> Any:
        """Build the target adapter for a stream from query params.

        Defaults to an everyday-style DemoAdapter (runs offline). If a config is
        named/pathed and resolvable, builds the configured adapter instead.
        """
        from promptpolygraph.adapters import DemoAdapter, build_adapter
        from promptpolygraph.config import Config

        cfg_path = None
        cp = (query.get("config_path", [""])[0] or "").strip()
        if cp:
            p = Path(cp).expanduser()
            if p.is_file():
                cfg_path = str(p.resolve())
        if cfg_path is None:
            name = (query.get("config_name", [""])[0] or "").strip()
            if name:
                cfg_path = self._resolve_config_path({"config_name": name})
        if cfg_path:
            try:
                return build_adapter(Config.load(cfg_path).adapter)
            except Exception:
                pass  # fall back to the demo target
        return DemoAdapter(style="everyday")

    def _api_redteam_stream(self, query: dict[str, list[str]]) -> None:
        """Stream a red-team run as Server-Sent Events.

        Runs ``run_redteam`` in a worker thread whose ``emit`` callback pushes
        ``RedTeamEvent`` frames into a queue; this handler drains the queue and
        writes ``ev.to_sse()`` frames until a terminal ``done``/``error`` event,
        then closes. The worker never blocks the server, and a client disconnect
        is tolerated (the next write raises and we stop).
        """
        from promptpolygraph.redteam import RedTeamEvent, get_profile, run_redteam

        profile_name = (query.get("profile", ["all_frontier"])[0] or "all_frontier").strip() or "all_frontier"
        mock_raw = (query.get("mock", ["1"])[0] or "1").strip().lower()
        mock = mock_raw not in ("0", "false", "no", "")
        mock = _want_mock(mock)  # force offline when no key is configured
        sources = [s.strip() for s in (query.get("sources", [""])[0] or "").split(",") if s.strip()]

        try:
            profile = get_profile(profile_name)
        except Exception:
            profile = get_profile("all_frontier")

        try:
            adapter = self._redteam_target(query)
        except Exception:
            from promptpolygraph.adapters import DemoAdapter

            adapter = DemoAdapter(style="everyday")

        # Open the SSE response.
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except Exception:
            return

        evq: queue.Queue[Any] = queue.Queue(maxsize=2048)
        _SENTINEL = object()
        collected: list[Any] = []  # full event log, persisted for replay

        def _emit(ev: RedTeamEvent) -> None:
            collected.append(ev)
            try:
                evq.put(ev, timeout=5.0)
            except Exception:
                pass  # drop on backpressure rather than stall the worker

        def _worker() -> None:
            try:
                report = asyncio.run(run_redteam(adapter, profile, emit=_emit, mock=mock, concurrency=4,
                                                  extra_sources=sources))
                try:
                    self._persist_redteam_run(report, collected)
                except Exception:
                    pass  # persistence is best-effort; the live stream already happened
            except Exception as exc:
                try:
                    evq.put(RedTeamEvent(type="error", text=str(exc),
                                         data={"message": str(exc)}), timeout=2.0)
                except Exception:
                    pass
            finally:
                try:
                    evq.put(_SENTINEL, timeout=2.0)
                except Exception:
                    pass

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        # Drain the queue -> SSE frames. Stop on the sentinel, a terminal event,
        # or a client disconnect (write raises).
        try:
            # An initial comment frame opens the pipe promptly for the client.
            self.wfile.write(b": arena stream open\n\n")
            self.wfile.flush()
            while True:
                try:
                    item = evq.get(timeout=30.0)
                except queue.Empty:
                    # heartbeat so proxies/clients keep the connection
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    if not worker.is_alive() and evq.empty():
                        break
                    continue
                if item is _SENTINEL:
                    break
                self.wfile.write(item.to_sse().encode("utf-8"))
                self.wfile.flush()
                if getattr(item, "type", None) in ("done", "error"):
                    break
        except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
            pass  # client went away — let the daemon worker finish on its own
        except Exception:
            pass

    # ---- providers (drives the provider/model dropdowns) ---------------
    def _api_providers(self) -> None:
        from promptpolygraph.discovery import discover_providers

        try:
            self._json(discover_providers())
        except Exception as exc:
            self._json({"error": "discovery failed", "detail": str(exc)}, status=500)

    # ---- studio: prompt-corpus generation + export ---------------------
    def _corpus_dir(self) -> Path:
        d = self.out_dir / "corpus"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _api_corpus_generate(self) -> None:
        """Generate a prompt corpus in the Studio (varied / adversarial / hybrid).

        Defaults to a frontier backend but honors any provider/model (incl. local
        Ollama) — the same pluggable client as the rest of the tool. Saves a
        loadable corpus dir under out_dir/corpus/<slug>/ and returns a preview."""
        from promptpolygraph.config import CorpusConfig
        from promptpolygraph.corpus import build_corpus

        body = self._read_body()

        def _int(v: Any) -> int | None:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        mode = (body.get("mode") or "varied").strip()
        domain = (str(body.get("domain") or "").strip()) or None
        provider = (body.get("provider") or "anthropic").strip().lower()
        model = body.get("model") or None
        base_url = body.get("base_url") or None
        difficulty = (body.get("difficulty") or "standard").strip()
        cats = body.get("categories")
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(",") if c.strip()]
        cats = [str(c) for c in cats] if isinstance(cats, list) else []

        mock = _want_mock(bool(body.get("mock")))
        client = None
        if not mock:
            try:
                from promptpolygraph.llm import make_client

                client = make_client(model, provider=provider, base_url=base_url)
            except Exception:
                client, mock = None, True

        cfg = CorpusConfig(mode=mode, count=_int(body.get("count")),
                           per_category=_int(body.get("per_category")),
                           categories=cats, difficulty=difficulty, seed=_int(body.get("seed")))
        try:
            cases = build_corpus(cfg, resolve=lambda p: p, client=client, mock=mock, domain=domain)
        except Exception as exc:
            self._json({"error": "generation failed", "detail": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        slug = _slugify(domain or mode, fallback="corpus")
        out = self._corpus_dir() / slug
        out.mkdir(parents=True, exist_ok=True)
        by_cat: dict[str, list[dict]] = {}
        for c in cases:
            by_cat.setdefault(c.category, []).append(c.model_dump(mode="json"))
        for cat, rows in by_cat.items():
            (out / f"{cat}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

        self._json({
            "path": str(out),
            "count": len(cases),
            "categories": {k: len(v) for k, v in by_cat.items()},
            "mode": mode,
            "provider": "mock" if mock else provider,
            "preview": [{"prompt": c.prompt, "category": c.category} for c in cases[:40]],
        })

    def _api_corpus_generate_stream(self, query: dict[str, list[str]]) -> None:
        """Generate a corpus and stream progress as SSE: plan -> batch/prompt … ->
        result. Lets the Studio show generation steps + prompts appearing live."""
        from promptpolygraph.config import CorpusConfig
        from promptpolygraph.corpus import build_corpus

        def q1(k: str, d: str = "") -> str:
            return (query.get(k, [d])[0] or d)

        def qint(k: str) -> int | None:
            v = q1(k)
            try:
                return int(v) if v not in ("", None) else None
            except (TypeError, ValueError):
                return None

        mode = q1("mode", "varied").strip() or "varied"
        domain = q1("domain").strip() or None
        provider = (q1("provider", "anthropic").strip().lower()) or "anthropic"
        model = q1("model") or None
        base_url = q1("base_url") or None
        difficulty = q1("difficulty", "standard").strip() or "standard"
        cats = [c.strip() for c in q1("categories").split(",") if c.strip()]
        mock = q1("mock", "1").strip().lower() not in ("0", "false", "no", "")
        mock = _want_mock(mock)
        client = None
        if not mock:
            try:
                from promptpolygraph.llm import make_client

                client = make_client(model, provider=provider, base_url=base_url)
            except Exception:
                client, mock = None, True
        cfg = CorpusConfig(mode=mode, count=qint("count"), per_category=qint("per_category"),
                           categories=cats, difficulty=difficulty, seed=qint("seed"))

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except Exception:
            return

        evq: queue.Queue[Any] = queue.Queue(maxsize=4096)
        _SENTINEL = object()

        def _frame(stage: str, data: dict) -> bytes:
            return f"event: {stage}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

        def _prog(stage: str, info: dict) -> None:
            try:
                evq.put((stage, info), timeout=5.0)
            except Exception:
                pass

        def _worker() -> None:
            try:
                cases = build_corpus(cfg, resolve=lambda p: p, client=client, mock=mock,
                                     domain=domain, progress=_prog)
                slug = _slugify(domain or mode, fallback="corpus")
                out = self._corpus_dir() / slug
                out.mkdir(parents=True, exist_ok=True)
                by_cat: dict[str, list[dict]] = {}
                for c in cases:
                    by_cat.setdefault(c.category, []).append(c.model_dump(mode="json"))
                for cat, rows in by_cat.items():
                    (out / f"{cat}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
                evq.put(("result", {
                    "path": str(out), "count": len(cases),
                    "categories": {k: len(v) for k, v in by_cat.items()},
                    "mode": mode, "provider": "mock" if mock else provider,
                    "preview": [{"prompt": c.prompt, "category": c.category} for c in cases[:40]],
                }), timeout=5.0)
            except Exception as exc:
                try:
                    evq.put(("error", {"error": str(exc)}), timeout=2.0)
                except Exception:
                    pass
            finally:
                try:
                    evq.put(_SENTINEL, timeout=2.0)
                except Exception:
                    pass

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        try:
            self.wfile.write(b": corpus stream open\n\n")
            self.wfile.flush()
            while True:
                try:
                    item = evq.get(timeout=30.0)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    if not worker.is_alive() and evq.empty():
                        break
                    continue
                if item is _SENTINEL:
                    break
                stage, data = item
                self.wfile.write(_frame(stage, data))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
            pass
        except Exception:
            pass

    def _api_corpus_dir_export(self, query: dict[str, list[str]]) -> None:
        """Download a generated corpus dir as json | jsonl | csv. Bounded to
        out_dir/corpus so it can't read arbitrary paths."""
        import csv
        import io

        from promptpolygraph.corpus import load_corpus

        want = (query.get("path", [""])[0] or "").strip()
        if not want:
            self._not_found("path required")
            return
        rp = Path(want).expanduser().resolve()
        root = (self.out_dir / "corpus").resolve()
        if rp != root and root not in rp.parents:
            self._not_found("path outside the generated-corpus area")
            return
        try:
            cases = load_corpus(str(rp))
        except Exception:
            self._not_found("could not load corpus")
            return
        fmt = (query.get("format", ["json"])[0] or "json").lower()
        prompts_only = (query.get("prompts_only", ["0"])[0] or "0").lower() in ("1", "true", "yes")
        if prompts_only:
            rows: list[Any] = [{"prompt": c.prompt, "category": c.category} for c in cases]
        else:
            rows = [c.model_dump(mode="json", exclude={"id"}) for c in cases]
        if fmt == "json":
            data = json.dumps(rows, indent=2, ensure_ascii=False).encode("utf-8")
            ctype = "application/json"
        elif fmt == "jsonl":
            data = ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")
            ctype = "application/x-ndjson"
        elif fmt == "csv":
            buf = io.StringIO()
            cols = ["prompt", "category", "subcategory", "expected_shape", "expected_behavior"]
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for c in cases:
                w.writerow({"prompt": c.prompt, "category": c.category,
                            "subcategory": getattr(c, "subcategory", None) or "",
                            "expected_shape": getattr(c, "expected_shape", None) or "",
                            "expected_behavior": getattr(c, "expected_behavior", None) or ""})
            data = buf.getvalue().encode("utf-8")
            ctype = "text/csv"
        else:
            self._not_found("unknown corpus format")
            return
        self._send_download(data, f"{rp.name}-corpus.{fmt}", ctype)

    # ---- red-team run persistence + replay + on-demand code trace -------
    def _redteam_dir(self) -> Path:
        d = self.out_dir / "redteam"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist_redteam_run(self, report: Any, events: list[Any]) -> None:
        """Save a completed Arena run so it can be replayed + drilled into."""
        from promptpolygraph.redteam.report import render_html, render_json, render_md

        rd = self._redteam_dir() / report.run_id
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "report.json").write_text(
            json.dumps(render_json(report), indent=2, ensure_ascii=False), encoding="utf-8")
        (rd / "events.jsonl").write_text(
            "\n".join(e.model_dump_json() for e in events), encoding="utf-8")
        try:
            (rd / "report.md").write_text(render_md(report), encoding="utf-8")
            (rd / "report.html").write_text(render_html(report), encoding="utf-8")
        except Exception:
            pass  # report rendering is a convenience; the json + events are the record

    def _api_redteam_runs(self) -> None:
        base = self.out_dir / "redteam"
        out: list[dict[str, Any]] = []
        if base.is_dir():
            for d in base.iterdir():
                f = d / "report.json"
                if not f.is_file():
                    continue
                try:
                    rep = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                st = rep.get("stats", {}) or {}
                out.append({
                    "run_id": rep.get("run_id", d.name),
                    "profile": rep.get("profile"),
                    "target": rep.get("target"),
                    "created_at": rep.get("created_at"),
                    "asr": st.get("asr"),
                    "breaches": st.get("breaches"),
                    "attacks": st.get("attacks"),
                    "vulnerabilities": len(rep.get("vulnerabilities", [])),
                })
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)  # newest first
        self._json(out)

    def _api_redteam_run(self, run_id: str) -> None:
        f = self.out_dir / "redteam" / run_id / "report.json"
        if not f.is_file():
            self._not_found("red-team run not found")
            return
        try:
            rep = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            self._not_found("could not read red-team run")
            return
        from promptpolygraph.redteam.models import AttackAttempt
        from promptpolygraph.redteam.rootcause import attacker_timeline

        by_attacker: dict[str, list[dict]] = {}
        for ad in rep.get("attempts", []):
            by_attacker.setdefault(ad.get("attacker_id", "?"), []).append(ad)
        attackers: list[dict[str, Any]] = []
        for aid, ads in by_attacker.items():
            try:
                objs = [AttackAttempt.model_validate(a) for a in ads]
            except Exception:
                continue
            tl = attacker_timeline(objs)
            attackers.append({
                "attacker_id": aid,
                "strategy": objs[0].strategy if objs else None,
                "breached": any(o.verdict and o.verdict.breached for o in objs),
                **tl,
            })
        self._json({"report": rep, "attackers": attackers})

    def _api_redteam_events(self, run_id: str) -> None:
        f = self.out_dir / "redteam" / run_id / "events.jsonl"
        events: list[Any] = []
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
        self._json(events)

    def _api_redteam_trace(self) -> None:
        """On-demand code-grounded root-cause for one finding.

        IP posture: the code-dive defaults to a LOCAL model (source never leaves
        the machine). A non-local provider is refused outright when air-gap is on
        (POLYGRAPH_AIR_GAP=1) and otherwise requires explicit `consent` in the body.
        """
        body = self._read_body()
        run_id = str(body.get("run_id") or "").strip()
        if not run_id:
            self._json({"error": "run_id required"}, status=HTTPStatus.BAD_REQUEST)
            return
        f = self.out_dir / "redteam" / run_id / "report.json"
        if not f.is_file():
            self._not_found("red-team run not found")
            return
        try:
            rep = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            self._not_found("could not read red-team run")
            return

        attempts = rep.get("attempts", [])
        attempt_id = body.get("attempt_id")
        attacker_id = body.get("attacker_id")
        chosen = None
        if attempt_id:
            chosen = next((a for a in attempts if a.get("id") == attempt_id), None)
        elif attacker_id:
            cand = [a for a in attempts if a.get("attacker_id") == attacker_id]
            chosen = next((a for a in cand if (a.get("verdict") or {}).get("breached")), None) \
                or (cand[-1] if cand else None)
        else:
            chosen = next((a for a in attempts if (a.get("verdict") or {}).get("breached")), None) \
                or (attempts[-1] if attempts else None)
        if not chosen:
            self._json({"error": "no attempts to trace in this run"}, status=HTTPStatus.NOT_FOUND)
            return

        provider = (body.get("provider") or "ollama").strip().lower()
        model = body.get("model") or None
        base_url = body.get("base_url") or None
        consent = bool(body.get("consent"))
        mock = bool(body.get("mock"))
        code_path = (str(body.get("code_path") or "").strip()) or None

        local_providers = {"ollama", "vllm", "lmstudio"}
        air_gap = os.environ.get("POLYGRAPH_AIR_GAP", "").strip().lower() in ("1", "true", "yes")
        if provider not in local_providers and not mock:
            if air_gap:
                self._json({"error": "air-gap is on — code dives are restricted to a local model",
                            "provider": provider}, status=HTTPStatus.FORBIDDEN)
                return
            if not consent:
                self._json({"error": f"sending source excerpts to '{provider}' requires explicit consent",
                            "needs_consent": True, "provider": provider}, status=HTTPStatus.BAD_REQUEST)
                return

        from promptpolygraph.redteam.codetrace import trace_in_code
        from promptpolygraph.redteam.models import AttackAttempt

        try:
            attempt = AttackAttempt.model_validate(chosen)
        except Exception as exc:
            self._json({"error": "bad attempt record", "detail": str(exc)}, status=500)
            return

        client = None
        if not mock:
            try:
                from promptpolygraph.llm import make_client

                client = make_client(model, provider=provider, base_url=base_url)
            except Exception:
                client, mock = None, True

        try:
            result = asyncio.run(trace_in_code(attempt, code_path=code_path, client=client, mock=mock))
        except Exception as exc:
            self._json({"error": "trace failed", "detail": str(exc)}, status=500)
            return
        result["provider"] = "mock" if mock else provider
        self._json(result)

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
