"""SARIF 2.1.0 output — the OASIS standard static-analysis interchange format.

SARIF is what GitHub code-scanning, GitLab, and Azure DevOps ingest to render
findings inline on a PR with file:line annotations. Emitting it makes a
PromptPolygraph red-team or eval run a first-class security check: each breach
becomes a SARIF *result* with a severity-mapped level and — when a code-grounded
trace is supplied — a physical location pointing at the source line where the
weakness was introduced.

Pure stdlib (``json``). The output validates against the SARIF 2.1.0 schema.
"""

from __future__ import annotations

import json
from typing import Any

from .. import __version__
from ..models import Case, Response, RunMeta, Score

_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_INFO_URI = "https://github.com/justinkastil/promptpolygraph"

# severity -> SARIF result level
_LEVEL = {"critical": "error", "high": "error", "medium": "warning",
          "low": "note", "none": "note"}


def _driver(rules: list[dict]) -> dict:
    return {
        "name": "PromptPolygraph",
        "informationUri": _INFO_URI,
        "version": __version__,
        "rules": rules,
    }


def _location(path: str | None, start_line: int | None, end_line: int | None = None) -> list[dict]:
    if not path:
        return []
    region: dict[str, Any] = {}
    if start_line:
        region["startLine"] = int(start_line)
        if end_line:
            region["endLine"] = int(end_line)
    loc: dict[str, Any] = {"physicalLocation": {"artifactLocation": {"uri": path}}}
    if region:
        loc["physicalLocation"]["region"] = region
    return [loc]


def _parse_lines(lines: Any) -> tuple[int | None, int | None]:
    """Parse a '12-20' or '12' line spec into (start, end)."""
    if lines is None:
        return (None, None)
    s = str(lines).strip()
    if "-" in s:
        a, _, b = s.partition("-")
        try:
            return (int(a), int(b))
        except ValueError:
            return (None, None)
    try:
        return (int(s), None)
    except ValueError:
        return (None, None)


def _sarif_doc(driver: dict, results: list[dict]) -> str:
    return json.dumps({
        "version": "2.1.0",
        "$schema": _SCHEMA,
        "runs": [{"tool": {"driver": driver}, "results": results}],
    }, indent=2)


def render_sarif_eval(
    run_meta: RunMeta,
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict[str, Any],
) -> str:
    """Render an evaluation run as SARIF: each failing case is a `warning`
    result keyed by category, with the gate threshold in the rule help."""
    score_by_id = {s.case_id: s for s in scores}
    threshold = summary.get("threshold")
    cats = sorted({c.category or "default" for c in cases})
    rules = [{
        "id": f"eval/{cat}",
        "name": f"Eval-{cat}",
        "shortDescription": {"text": f"Evaluation gate for category '{cat}'"},
        "helpUri": _INFO_URI,
        "properties": {"category": cat, "threshold": threshold},
    } for cat in cats]

    results: list[dict] = []
    for c in cases:
        score = score_by_id.get(c.id)
        if score is None or score.verdict_pass:
            continue
        low = [f"{d}={v}" for d, v in (score.dimensions or {}).items() if v is not None]
        reason = score.failure_reason or ("below threshold " + str(threshold))
        results.append({
            "ruleId": f"eval/{c.category or 'default'}",
            "level": "warning",
            "message": {"text": f"Case failed the gate: {reason}. "
                                f"{('dims ' + ', '.join(low)) if low else ''}".strip()},
            "properties": {"case_id": c.id, "category": c.category,
                           "prompt": c.prompt[:300]},
        })
    return _sarif_doc(_driver(rules), results)


def render_sarif_redteam(report: Any, *, traces: dict[str, dict] | None = None) -> str:
    """Render a red-team report as SARIF: each vulnerability is a result whose
    level maps from its severity. When `traces` supplies a code-grounded trace
    for a vuln class (``{vuln_class: {introduced_file, introduced_lines}}``), the
    result carries the source file:line where the weakness was introduced.
    """
    traces = traces or {}
    vulns = list(getattr(report, "vulnerabilities", []) or [])

    rules: list[dict] = []
    seen: set[str] = set()
    for v in vulns:
        if v.vuln_class in seen:
            continue
        seen.add(v.vuln_class)
        rules.append({
            "id": f"redteam/{v.vuln_class}",
            "name": v.vuln_class.replace("_", "-"),
            "shortDescription": {"text": f"Red-team finding: {v.vuln_class}"},
            "helpUri": _INFO_URI,
            "properties": {k: val for k, val in
                           (("owasp", v.owasp), ("atlas", v.atlas)) if val},
        })

    results: list[dict] = []
    for v in vulns:
        trace = traces.get(v.vuln_class) or {}
        start, end = _parse_lines(trace.get("introduced_lines"))
        locations = _location(trace.get("introduced_file"), start, end)
        tags = [t for t in (v.owasp, v.atlas) if t]
        msg = (f"{v.severity.upper()} — {v.vuln_class}: {v.count} breach"
               f"{'es' if v.count != 1 else ''}."
               f"{(' [' + ', '.join(tags) + ']') if tags else ''}"
               f"{(' Mitigation: ' + v.mitigation) if v.mitigation else ''}")
        result: dict[str, Any] = {
            "ruleId": f"redteam/{v.vuln_class}",
            "level": _LEVEL.get(v.severity, "warning"),
            "message": {"text": msg},
            "properties": {"severity": v.severity, "count": v.count,
                           "owasp": v.owasp, "atlas": v.atlas},
        }
        if locations:
            result["locations"] = locations
        results.append(result)
    return _sarif_doc(_driver(rules), results)
