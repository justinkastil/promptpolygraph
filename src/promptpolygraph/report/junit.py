"""JUnit XML output — the lingua franca CI systems parse into test results.

A polygraph run maps cleanly onto the JUnit model: a category is a ``testsuite``
and each case (or red-team attempt) is a ``testcase`` that *fails* when it misses
the gate (or is breached). GitHub Actions, GitLab CI, Jenkins, CircleCI, and most
test reporters ingest this directly, so an eval/red-team run shows up as native
test results in the pipeline with no bespoke parsing.

Pure stdlib (``xml.etree``), so escaping is correct and there are no deps.
"""

from __future__ import annotations

from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from ..models import Case, Response, RunMeta, Score


def _pretty(root: Element) -> str:
    raw = tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def _case_failure_message(score: Score | None) -> str | None:
    """A short human failure summary for a case, or None when it passed."""
    if score is None:
        return "no score (case not analyzed)"
    if score.verdict_pass:
        return None
    parts: list[str] = []
    if score.assertions_passed is False:
        failed = [a.kind for a in (score.assertions or []) if not a.passed]
        parts.append("assertions failed: " + (", ".join(failed) or "unknown"))
    low = [f"{d}={v}" for d, v in (score.dimensions or {}).items() if v is not None]
    if low:
        parts.append("dimensions: " + ", ".join(low))
    if score.failure_reason:
        parts.append(score.failure_reason)
    return " | ".join(parts) or "below gate threshold"


def render_junit_eval(
    run_meta: RunMeta,
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    summary: dict[str, Any],
) -> str:
    """Render an evaluation run as JUnit XML (one testsuite per category)."""
    score_by_id = {s.case_id: s for s in scores}
    resp_by_id = {r.case_id: r for r in responses}

    by_cat: dict[str, list[Case]] = {}
    for c in cases:
        by_cat.setdefault(c.category or "default", []).append(c)

    suites = Element("testsuites", name=run_meta.name or "polygraph")
    total_tests = total_failures = total_errors = 0

    for cat in sorted(by_cat):
        cat_cases = by_cat[cat]
        suite = SubElement(suites, "testsuite", name=cat, tests=str(len(cat_cases)))
        s_fail = s_err = 0
        for c in cat_cases:
            score = score_by_id.get(c.id)
            resp = resp_by_id.get(c.id)
            latency_s = ((resp.latency_ms or 0) / 1000.0) if resp else 0.0
            tc = SubElement(suite, "testcase", name=c.id, classname=f"polygraph.{cat}",
                            time=f"{latency_s:.3f}")
            if resp is not None and resp.error:
                err = SubElement(tc, "error", message=str(resp.error)[:200], type="AdapterError")
                err.text = str(resp.error)
                s_err += 1
            else:
                msg = _case_failure_message(score)
                if msg is not None:
                    fail = SubElement(tc, "failure", message=msg[:200], type="GateFailure")
                    fail.text = f"prompt: {c.prompt}\n{msg}"
                    s_fail += 1
        suite.set("failures", str(s_fail))
        suite.set("errors", str(s_err))
        total_tests += len(cat_cases)
        total_failures += s_fail
        total_errors += s_err

    suites.set("tests", str(total_tests))
    suites.set("failures", str(total_failures))
    suites.set("errors", str(total_errors))
    return _pretty(suites)


def render_junit_redteam(report: Any) -> str:
    """Render a red-team report as JUnit XML (one testsuite per strategy).

    A breached attempt is a test *failure*; the failure message carries the
    severity, OWASP/ATLAS mapping, and the judge's rationale.
    """
    attempts = list(getattr(report, "attempts", []) or [])
    # vuln class -> standards, for enriching the failure message.
    std_by_class: dict[str, tuple[str | None, str | None]] = {}
    for v in getattr(report, "vulnerabilities", []) or []:
        std_by_class[v.vuln_class] = (v.owasp, v.atlas)

    by_strategy: dict[str, list[Any]] = {}
    for a in attempts:
        by_strategy.setdefault(a.strategy or "attack", []).append(a)

    suites = Element("testsuites", name=f"redteam:{getattr(report, 'profile', '') or 'custom'}")
    total_tests = total_failures = 0
    for strat in sorted(by_strategy):
        atts = by_strategy[strat]
        suite = SubElement(suites, "testsuite", name=strat, tests=str(len(atts)))
        s_fail = 0
        for a in atts:
            tc = SubElement(suite, "testcase", name=f"{a.id}",
                            classname=f"redteam.{strat}", time=f"{(a.latency_ms or 0) / 1000.0:.3f}")
            ver = getattr(a, "verdict", None)
            if ver is not None and ver.breached:
                cls = ver.vuln_class or strat
                owasp, atlas = std_by_class.get(cls, (None, None))
                tags = " ".join(t for t in (owasp, atlas) if t)
                msg = f"[{ver.severity}] {cls}{(' — ' + tags) if tags else ''}"
                fail = SubElement(tc, "failure", message=msg[:200], type="Breach")
                fail.text = (f"turn {a.turn}\nprobe: {a.prompt}\nresponse: {a.response}\n"
                             f"judge: {ver.rationale or ''}")
                s_fail += 1
        suite.set("failures", str(s_fail))
        suite.set("errors", "0")
        total_tests += len(atts)
        total_failures += s_fail
    suites.set("tests", str(total_tests))
    suites.set("failures", str(total_failures))
    suites.set("errors", "0")
    return _pretty(suites)
