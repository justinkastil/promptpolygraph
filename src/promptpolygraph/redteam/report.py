"""Vulnerability-report rendering for a red-team run.

This is for **authorized red-teaming of a system you own** — the output is a
severity-ranked vulnerability report with mitigations, not weaponized content.

`render_md(report)` and `render_html(report)` produce a header (profile/target +
a one-line verdict), a severity-ranked vulnerability table, and per-vulnerability
the example attempts (probe -> response -> judge rationale/evidence). The HTML is
fully self-contained (inline CSS, no external assets) and severity color-coded;
all text is escaped. `render_json(report)` returns a plain dict.
"""

from __future__ import annotations

from html import escape as _esc
from typing import Any

from .models import RedTeamReport, severity_rank

# Severity ordering high -> low for display.
_SEV_DISPLAY = ["critical", "high", "medium", "low", "none"]

# console / markdown verdict glyphs handled in the CLI; here we keep it textual.


def _by_id(report: RedTeamReport) -> dict[str, Any]:
    return {a.id: a for a in report.attempts}


def _verdict_line(report: RedTeamReport) -> str:
    st = report.stats or {}
    attacks = st.get("attacks", len(report.attempts))
    breaches = st.get("breaches", 0)
    by_sev = st.get("by_severity", {}) or {}
    parts = [f"{by_sev[s]} {s}" for s in _SEV_DISPLAY if by_sev.get(s)]
    sev_str = ", ".join(parts) if parts else "no breaches"
    return f"{breaches}/{attacks} attacks breached ({sev_str})"


def _trim(text: str | None, n: int = 600) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# ─── Markdown ────────────────────────────────────────────────────────────────


def render_md(report: RedTeamReport) -> str:
    st = report.stats or {}
    by_id = _by_id(report)
    out: list[str] = []
    out.append(f"# Red-Team Vulnerability Report — {report.target or 'target'}")
    out.append("")
    out.append(f"*Authorized red-teaming of a system you own.*")
    out.append("")
    out.append(f"- **Profile:** {report.profile or '(custom)'}")
    out.append(f"- **Target:** {report.target or '(unknown)'}")
    out.append(f"- **Run:** {report.run_id}")
    out.append(f"- **Attackers:** {st.get('attackers', '?')}")
    out.append("")
    highest = report.vulnerabilities[0].severity if report.vulnerabilities else "none"
    out.append(f"## Verdict: {_verdict_line(report)} — highest severity **{highest.upper()}**")
    out.append("")

    # Severity-ranked vulnerability table.
    out.append("## Vulnerabilities (severity-ranked)")
    out.append("")
    if not report.vulnerabilities:
        out.append("No vulnerabilities found — the target defended every probe.")
        out.append("")
    else:
        out.append("| Severity | Vulnerability class | Count | Mitigation |")
        out.append("| --- | --- | ---: | --- |")
        for v in report.vulnerabilities:
            mit = (v.mitigation or "").replace("\n", " ").replace("|", "\\|")
            cls = v.vuln_class.replace("|", "\\|")
            out.append(f"| {v.severity.upper()} | {cls} | {v.count} | {mit or '—'} |")
        out.append("")

        # Per-vulnerability example attempts.
        out.append("## Findings")
        out.append("")
        for v in report.vulnerabilities:
            out.append(f"### {v.severity.upper()} — {v.vuln_class} ({v.count} breach"
                       f"{'es' if v.count != 1 else ''})")
            out.append("")
            if v.mitigation:
                out.append(f"**Mitigation:** {v.mitigation}")
                out.append("")
            for aid in v.example_attempt_ids:
                att = by_id.get(aid)
                if not att:
                    continue
                ver = att.verdict
                out.append(f"- **Attempt `{att.id}`** — strategy `{att.strategy}`, turn {att.turn}")
                out.append(f"  - *Probe:* {_trim(att.prompt)}")
                out.append(f"  - *Response:* {_trim(att.response)}")
                if ver:
                    if ver.rationale:
                        out.append(f"  - *Judge:* {ver.rationale}")
                    if ver.evidence:
                        out.append(f"  - *Evidence:* {_trim(ver.evidence, 300)}")
                out.append("")

    return "\n".join(out).rstrip() + "\n"


# ─── HTML ────────────────────────────────────────────────────────────────────


def _e(v: Any) -> str:
    if v is None:
        return "&mdash;"
    return _esc(str(v))


_CSS = """
:root {
  --fg:#1c1c1e; --muted:#6b6b70; --bg:#fff; --panel:#f6f6f8; --border:#d9d9de;
  --crit:#7a0b0b; --high:#b01b1b; --med:#c2680a; --low:#b8860b; --none:#1b7f37;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
body { margin:0; padding:0 0 4rem; color:var(--fg); background:var(--bg);
  font:15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.wrap { max-width:960px; margin:0 auto; padding:2rem 1.25rem; }
h1 { font-size:1.8rem; margin:0 0 .25rem; }
h2 { font-size:1.35rem; margin:2rem 0 .75rem; padding-bottom:.3rem; border-bottom:2px solid var(--border); }
h3 { font-size:1.1rem; margin:1.4rem 0 .5rem; }
.muted { color:var(--muted); }
.cover dl { display:grid; grid-template-columns:max-content 1fr; gap:.15rem 1rem; margin:1rem 0; }
.cover dt { font-weight:600; color:var(--muted); }
.cover dd { margin:0; }
.verdict { font-size:1.2rem; font-weight:700; margin:1rem 0; padding:.75rem 1rem; border-radius:8px;
  background:var(--panel); border-left:6px solid var(--border); }
table { border-collapse:collapse; width:100%; margin:1rem 0; font-size:.93rem; }
th, td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--border); vertical-align:top; }
th { color:var(--muted); font-weight:600; }
td.num { text-align:right; }
.pill { display:inline-block; padding:.1rem .55rem; border-radius:999px; font-size:.72rem;
  font-weight:700; letter-spacing:.03em; color:#fff; text-transform:uppercase; }
.sev-critical { background:var(--crit); } .verdict.sev-critical { border-left-color:var(--crit); color:var(--crit); }
.sev-high { background:var(--high); } .verdict.sev-high { border-left-color:var(--high); color:var(--high); }
.sev-medium { background:var(--med); } .verdict.sev-medium { border-left-color:var(--med); color:var(--med); }
.sev-low { background:var(--low); } .verdict.sev-low { border-left-color:var(--low); color:var(--low); }
.sev-none { background:var(--none); } .verdict.sev-none { border-left-color:var(--none); color:var(--none); }
.finding { border:1px solid var(--border); border-radius:8px; padding:.9rem 1.1rem; margin:1rem 0; }
.finding.sev-critical, .finding.sev-high { border-left:6px solid var(--high); }
.finding.sev-critical { border-left-color:var(--crit); }
.finding.sev-medium { border-left:6px solid var(--med); }
.finding.sev-low { border-left:6px solid var(--low); }
.mit { background:var(--panel); border-radius:6px; padding:.5rem .75rem; margin:.5rem 0; }
.attempt { margin:.75rem 0; padding:.6rem .8rem; background:var(--panel); border-radius:6px; }
.attempt .lbl { font-weight:600; color:var(--muted); }
.attempt pre { font-family:var(--mono); font-size:.82rem; white-space:pre-wrap; word-break:break-word;
  margin:.15rem 0 .6rem; background:#fff; border:1px solid var(--border); border-radius:5px; padding:.4rem .55rem; }
""".strip()


def _sev_class(sev: str) -> str:
    return f"sev-{sev if sev in _SEV_DISPLAY else 'none'}"


def render_html(report: RedTeamReport) -> str:
    st = report.stats or {}
    by_id = _by_id(report)
    highest = report.vulnerabilities[0].severity if report.vulnerabilities else "none"

    h: list[str] = []
    h.append("<!doctype html>")
    h.append('<html lang="en"><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    h.append(f"<title>Red-Team Report — {_e(report.target)}</title>")
    h.append(f"<style>{_CSS}</style>")
    h.append("</head><body><div class='wrap'>")

    h.append(f"<h1>Red-Team Vulnerability Report</h1>")
    h.append("<p class='muted'>Authorized red-teaming of a system you own.</p>")
    h.append("<div class='cover'><dl>")
    h.append(f"<dt>Profile</dt><dd>{_e(report.profile or '(custom)')}</dd>")
    h.append(f"<dt>Target</dt><dd>{_e(report.target or '(unknown)')}</dd>")
    h.append(f"<dt>Run</dt><dd>{_e(report.run_id)}</dd>")
    h.append(f"<dt>Attackers</dt><dd>{_e(st.get('attackers'))}</dd>")
    h.append("</dl></div>")

    h.append(f"<div class='verdict {_sev_class(highest)}'>"
             f"{_e(_verdict_line(report))} &mdash; highest severity {_e(highest.upper())}</div>")

    h.append("<h2>Vulnerabilities (severity-ranked)</h2>")
    if not report.vulnerabilities:
        h.append("<p>No vulnerabilities found — the target defended every probe.</p>")
    else:
        h.append("<table><thead><tr><th>Severity</th><th>Vulnerability class</th>"
                 "<th class='num'>Count</th><th>Mitigation</th></tr></thead><tbody>")
        for v in report.vulnerabilities:
            h.append("<tr>"
                     f"<td><span class='pill {_sev_class(v.severity)}'>{_e(v.severity)}</span></td>"
                     f"<td>{_e(v.vuln_class)}</td>"
                     f"<td class='num'>{_e(v.count)}</td>"
                     f"<td>{_e(v.mitigation or '—')}</td></tr>")
        h.append("</tbody></table>")

        h.append("<h2>Findings</h2>")
        for v in report.vulnerabilities:
            h.append(f"<div class='finding {_sev_class(v.severity)}'>")
            h.append(f"<h3><span class='pill {_sev_class(v.severity)}'>{_e(v.severity)}</span> "
                     f"{_e(v.vuln_class)} "
                     f"<span class='muted'>({_e(v.count)} breach"
                     f"{'es' if v.count != 1 else ''})</span></h3>")
            if v.mitigation:
                h.append(f"<div class='mit'><strong>Mitigation:</strong> {_e(v.mitigation)}</div>")
            for aid in v.example_attempt_ids:
                att = by_id.get(aid)
                if not att:
                    continue
                ver = att.verdict
                h.append("<div class='attempt'>")
                h.append(f"<div><span class='lbl'>Attempt {_e(att.id)}</span> "
                         f"<span class='muted'>strategy {_e(att.strategy)}, turn {_e(att.turn)}</span></div>")
                h.append(f"<div class='lbl'>Probe</div><pre>{_e(_trim(att.prompt))}</pre>")
                h.append(f"<div class='lbl'>Response</div><pre>{_e(_trim(att.response))}</pre>")
                if ver and ver.rationale:
                    h.append(f"<div class='lbl'>Judge</div><pre>{_e(ver.rationale)}</pre>")
                if ver and ver.evidence:
                    h.append(f"<div class='lbl'>Evidence</div><pre>{_e(_trim(ver.evidence, 300))}</pre>")
                h.append("</div>")
            h.append("</div>")

    h.append("</div></body></html>")
    return "\n".join(h)


# ─── JSON ────────────────────────────────────────────────────────────────────


def render_json(report: RedTeamReport) -> dict:
    return report.model_dump(mode="json")
