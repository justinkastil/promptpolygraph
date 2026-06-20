"""GitHub Actions (and generic) PR feedback from a run summary + baseline diff.

Two surfaces:

- **Workflow-command annotations** (``::error::`` / ``::warning::`` / ``::notice::``)
  that GitHub renders inline on the Checks tab.
- **Markdown** for a PR comment or the job summary (``$GITHUB_STEP_SUMMARY``):
  the gate verdict, per-dimension deltas vs the baseline, the worst-affected
  categories, and — when the confidence layer is present — which regressions are
  statistically significant and which sit inside the noise band.

Everything here is pure string/file work; the engine stays vendor-neutral and
the same markdown drops into a GitLab note or a Jenkins summary just as well.
"""

from __future__ import annotations

import os
from typing import Any


def _fmt(v: Any, places: int = 2) -> str:
    try:
        return f"{float(v):.{places}f}"
    except (TypeError, ValueError):
        return str(v)


def annotations(summary: dict[str, Any], baseline_diff: dict[str, Any] | None = None) -> list[str]:
    """GitHub Actions workflow-command lines for the gate result.

    A failing gate is an ``::error::``; a category whose CI band straddles the
    threshold (inconclusive) is a ``::warning::``; a statistically significant
    regression vs the baseline is an ``::error::``.
    """
    out: list[str] = []
    overall_pass = bool(summary.get("overall_pass"))
    band = (summary.get("gate_band") or {})
    by_cat_band = band.get("by_category") or {}

    if not overall_pass:
        failing = [c for c, e in (summary.get("category_scores") or {}).items()
                   if e.get("pass") is False]
        detail = f"failing categories: {', '.join(sorted(failing))}" if failing else "gate failed"
        out.append(f"::error title=PromptPolygraph gate failed::{detail}")

    for cat, verdict in by_cat_band.items():
        if verdict == "inconclusive":
            out.append(f"::warning title=Inconclusive ({cat})::"
                       f"category '{cat}' has a confidence band straddling the threshold — "
                       "more samples needed to call it")

    if baseline_diff:
        for r in baseline_diff.get("significant_regressions") or []:
            out.append(f"::error title=Significant regression::"
                       f"{r['category']}/{r['dimension']} {_fmt(r['baseline'])} -> "
                       f"{_fmt(r['current'])} ({_fmt(r['delta'])}, q={_fmt(r.get('q_value'), 3)})")
        # heuristic-only regressions (no significance data) as warnings
        sig_keys = {(r["category"], r["dimension"]) for r in (baseline_diff.get("significant_regressions") or [])}
        for r in baseline_diff.get("regressions") or []:
            if (r["category"], r["dimension"]) not in sig_keys:
                out.append(f"::warning title=Regression::"
                           f"{r['category']}/{r['dimension']} {_fmt(r['baseline'])} -> "
                           f"{_fmt(r['current'])} ({_fmt(r['delta'])})")
    return out


def emit_annotations(summary: dict[str, Any], baseline_diff: dict[str, Any] | None = None) -> int:
    """Print the annotations to stdout (where Actions parses them). Returns count."""
    lines = annotations(summary, baseline_diff)
    for ln in lines:
        print(ln)
    return len(lines)


def pr_comment_markdown(
    summary: dict[str, Any],
    baseline_diff: dict[str, Any] | None = None,
    *,
    run_id: str | None = None,
    title: str = "PromptPolygraph",
) -> str:
    """A markdown summary suitable for a PR comment or the job summary."""
    overall_pass = bool(summary.get("overall_pass"))
    band = (summary.get("gate_band") or {}).get("overall")
    verdict = "✅ PASS" if overall_pass else "❌ FAIL"
    if band == "inconclusive" and overall_pass:
        verdict = "🟡 PASS (inconclusive band)"

    lines: list[str] = [f"## {title} — {verdict}", ""]
    passing = summary.get("categories_passing", 0)
    total = summary.get("categories_total", 0)
    thr = summary.get("threshold")
    lines.append(f"- **Categories passing:** {passing}/{total}  ·  **Threshold:** {_fmt(thr, 1)}")
    if run_id:
        lines.append(f"- **Run:** `{run_id}`")

    apr = (summary.get("confidence") or {}).get("assertion_pass_rate")
    if apr and apr.get("n"):
        lines.append(f"- **Assertion pass rate:** {_fmt((apr['value'] or 0) * 100, 1)}% "
                     f"(95% CI {_fmt((apr['ci_lower'] or 0) * 100, 1)}–{_fmt((apr['ci_upper'] or 0) * 100, 1)}%, "
                     f"n={apr['n']})")

    warnings = (summary.get("confidence") or {}).get("warnings") or []
    for w in warnings:
        lines.append(f"- ⚠️ {w}")

    # Per-category score table.
    cat_scores = summary.get("category_scores") or {}
    dims = summary.get("dimensions") or []
    if cat_scores and dims:
        lines += ["", "| Category | " + " | ".join(dims) + " | Gate |",
                  "| --- | " + " | ".join("---:" for _ in dims) + " | :---: |"]
        for cat in sorted(cat_scores):
            e = cat_scores[cat]
            cells = [(_fmt(e.get(d)) if e.get(d) is not None else "—") for d in dims]
            mark = "✅" if e.get("pass") else "❌"
            lines.append(f"| {cat} | " + " | ".join(cells) + f" | {mark} |")

    # Baseline movement.
    if baseline_diff:
        regs = baseline_diff.get("regressions") or []
        imps = baseline_diff.get("improvements") or []
        sig = baseline_diff.get("significant_regressions") or []
        lines += ["", "### Change vs baseline", ""]
        sig_avail = (baseline_diff.get("significance") or {}).get("available")
        lines.append(f"- {len(regs)} regression(s), {len(imps)} improvement(s)"
                     + (f", **{len(sig)} statistically significant**" if sig_avail else
                        " (significance unavailable — baseline predates the CI layer)"))
        worst = sorted(regs, key=lambda r: r.get("delta", 0))[:5]
        if worst:
            lines += ["", "| Category/Dimension | Baseline | Current | Δ | Significant |",
                      "| --- | ---: | ---: | ---: | :---: |"]
            sig_keys = {(r["category"], r["dimension"]): r for r in sig}
            for r in worst:
                s = sig_keys.get((r["category"], r["dimension"]))
                flag = (f"yes (q={_fmt(s.get('q_value'), 3)})" if s else
                        ("no" if sig_avail else "—"))
                lines.append(f"| {r['category']}/{r['dimension']} | {_fmt(r['baseline'])} | "
                             f"{_fmt(r['current'])} | {_fmt(r['delta'])} | {flag} |")

    lines += ["", "<sub>Generated by PromptPolygraph. A change inside the confidence band is "
              "reported but does not fail the gate when <code>analyze.respect_ci</code> is set.</sub>"]
    return "\n".join(lines) + "\n"


def write_step_summary(markdown: str) -> bool:
    """Append markdown to the GitHub Actions job summary, if running in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
        return True
    except OSError:
        return False
