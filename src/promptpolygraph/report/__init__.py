"""Report module: render a polygraph run review in multiple formats.

The same review content is renderable as Markdown, a Word document (.docx), a
PDF (via headless LibreOffice or a reportlab fallback), and a self-contained
HTML file. `build_report` orchestrates the requested formats, writes each file
into `out_dir`, and returns a {format: path} map. The PDF path is produced by
rendering the .docx first and converting it; if conversion is unavailable, PDF
is silently omitted from the result and rendering continues.
"""

from __future__ import annotations

import os
from typing import Optional

from ..models import Case, Response, Rubric, RunMeta, Score
from .docx import render_docx
from .html import render_html
from .junit import render_junit_eval
from .markdown import render_markdown
from .pdf import render_pdf
from .sarif import render_sarif_eval

__all__ = ["build_report", "render_markdown", "render_docx", "render_html", "render_pdf",
           "render_junit_eval", "render_sarif_eval"]


_FILENAMES = {
    "md": "report.md",
    "docx": "report.docx",
    "pdf": "report.pdf",
    "html": "report.html",
    "junit": "report.junit.xml",
    "sarif": "report.sarif.json",
}


def build_report(
    run_meta: RunMeta,
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict,
    *,
    rubric: Rubric,
    audit: dict | None = None,
    baseline_diff: dict | None = None,
    pairwise: dict | None = None,
    formats: list[str] | None = None,
    out_dir: str,
    template: str = "default",
    template_dir: str | None = None,
    branding: dict | None = None,
) -> dict[str, str]:
    """Render the requested report formats and write them into `out_dir`.

    Returns a mapping of format name to the absolute file path written. The PDF
    format requires a .docx to convert; it is rendered on demand (even if "docx"
    is not itself requested) and omitted from the result if conversion is not
    available on this machine.
    """
    if formats is None:
        formats = ["md"]
    os.makedirs(out_dir, exist_ok=True)

    common = dict(
        rubric=rubric,
        audit=audit,
        baseline_diff=baseline_diff,
        pairwise=pairwise,
    )
    templated = dict(template=template, template_dir=template_dir, branding=branding)

    out: dict[str, str] = {}
    docx_bytes: Optional[bytes] = None

    def _docx() -> bytes:
        nonlocal docx_bytes
        if docx_bytes is None:
            docx_bytes = render_docx(run_meta, cases, responses, scores, summary, **common)
        return docx_bytes

    for fmt in formats:
        path = os.path.abspath(os.path.join(out_dir, _FILENAMES.get(fmt, f"report.{fmt}")))

        if fmt == "md":
            text = render_markdown(run_meta, cases, responses, scores, summary, **common, **templated)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            out["md"] = path

        elif fmt == "html":
            text = render_html(run_meta, cases, responses, scores, summary, **common, **templated)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            out["html"] = path

        elif fmt == "docx":
            with open(path, "wb") as fh:
                fh.write(_docx())
            out["docx"] = path

        elif fmt == "pdf":
            result = render_pdf(_docx(), path)
            if result:
                out["pdf"] = result
            # else: pdf gracefully omitted

        elif fmt == "junit":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render_junit_eval(run_meta, cases, responses, scores, summary))
            out["junit"] = path

        elif fmt == "sarif":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render_sarif_eval(run_meta, cases, responses, scores, summary))
            out["sarif"] = path

    return out
