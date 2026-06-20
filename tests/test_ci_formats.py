"""JUnit XML + SARIF machine-readable output for CI ingestion."""

from __future__ import annotations

import asyncio
import json
from xml.etree.ElementTree import fromstring

from promptpolygraph.adapters.demo import DemoAdapter
from promptpolygraph.analyze.gate import summarize
from promptpolygraph.models import Case, Dimension, Response, Rubric, Score
from promptpolygraph.report.junit import render_junit_eval, render_junit_redteam
from promptpolygraph.report.sarif import render_sarif_eval, render_sarif_redteam
from promptpolygraph.redteam.orchestrator import run_redteam
from promptpolygraph.redteam.profiles import get_profile


def _eval_fixture():
    rubric = Rubric(dimensions=[Dimension(name="quality")], threshold=7.0)
    cases = [Case(id="ok1", prompt="good", category="accuracy"),
             Case(id="bad1", prompt="bad", category="accuracy"),
             Case(id="err1", prompt="boom", category="safety")]
    responses = [Response(case_id="ok1", text="a", latency_ms=12),
                 Response(case_id="bad1", text="b", latency_ms=20),
                 Response(case_id="err1", text="", latency_ms=5, error="timeout")]
    scores = [
        Score(case_id="ok1", dimensions={"quality": 9}, verdict_pass=True, assertions_passed=True),
        Score(case_id="bad1", dimensions={"quality": 3}, verdict_pass=False,
              assertions_passed=True, failure_reason="weak answer"),
        Score(case_id="err1", dimensions={"quality": None}, verdict_pass=False),
    ]
    summary = summarize(cases, responses, scores, rubric)
    return cases, responses, scores, summary


def test_junit_eval_is_valid_xml_with_failures():
    cases, responses, scores, summary = _eval_fixture()
    from promptpolygraph.models import RunMeta
    xml = render_junit_eval(RunMeta(name="t"), cases, responses, scores, summary)
    root = fromstring(xml)
    assert root.tag == "testsuites"
    assert int(root.get("tests")) == 3
    # one gate failure (bad1) + one adapter error (err1)
    assert int(root.get("failures")) == 1
    assert int(root.get("errors")) == 1
    suites = {s.get("name"): s for s in root.findall("testsuite")}
    assert "accuracy" in suites and "safety" in suites
    # the failing case carries a <failure> with the reason
    acc = suites["accuracy"]
    fails = acc.findall(".//failure")
    assert any("weak answer" in (f.text or "") for f in fails)


def test_sarif_eval_structure():
    cases, responses, scores, summary = _eval_fixture()
    from promptpolygraph.models import RunMeta
    doc = json.loads(render_sarif_eval(RunMeta(name="t"), cases, responses, scores, summary))
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "PromptPolygraph"
    assert run["tool"]["driver"]["version"]  # non-empty
    # only failing cases become results (bad1); err1 has no score dims/verdict_pass False -> also a result
    rule_ids = {r["ruleId"] for r in run["results"]}
    assert all(rid.startswith("eval/") for rid in rule_ids)
    for r in run["results"]:
        assert r["level"] in {"error", "warning", "note"}
        assert r["message"]["text"]


def test_redteam_junit_and_sarif():
    report = asyncio.run(run_redteam(DemoAdapter(), get_profile("quick"), mock=True))

    xml = render_junit_redteam(report)
    root = fromstring(xml)
    assert root.tag == "testsuites"
    assert int(root.get("tests")) == len(report.attempts)

    doc = json.loads(render_sarif_redteam(report))
    assert doc["version"] == "2.1.0"
    results = doc["runs"][0]["results"]
    assert len(results) == len(report.vulnerabilities)
    for r in results:
        assert r["ruleId"].startswith("redteam/")
        assert r["level"] in {"error", "warning", "note"}


def test_redteam_sarif_includes_code_location_when_trace_supplied():
    report = asyncio.run(run_redteam(DemoAdapter(), get_profile("quick"), mock=True))
    if not report.vulnerabilities:
        return  # mock target defended everything in this profile; nothing to locate
    cls = report.vulnerabilities[0].vuln_class
    traces = {cls: {"introduced_file": "src/app/guard.py", "introduced_lines": "42-50"}}
    doc = json.loads(render_sarif_redteam(report, traces=traces))
    located = [r for r in doc["runs"][0]["results"] if "locations" in r]
    assert located, "expected at least one result with a physical location"
    loc = located[0]["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "src/app/guard.py"
    assert loc["region"]["startLine"] == 42 and loc["region"]["endLine"] == 50
