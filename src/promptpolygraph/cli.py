"""PromptPolygraph command-line interface.

Subcommands:
  run       corpus -> adapter -> store (the target queries)
  generate  synthesize a corpus (varied | adversarial) to files
  analyze   score a run's responses against the rubric
  audit     persona panel + forensic audit over a run
  report    render markdown / docx / pdf / html
  compare   A/B two runs (pairwise win/loss/tie)
  personas  list the library / create one / generate a panel
  redteam   authorized adversarial red-team of the target -> vuln report
  all       run -> analyze -> audit -> report, end to end

Everything is driven by a YAML config (see examples/support_bot/config.yaml)
with per-flag overrides. `--mock` (or absence of ANTHROPIC_API_KEY) runs the
whole pipeline offline with deterministic stand-ins for every LLM step.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import analyze as A
from . import audit as AU
from . import corpus as C
from . import persona as P
from .adapters import build_adapter
from .compare import compare_runs as compare_runs_fn
from .compare import pairwise as pairwise_fn
from .compare import trend as trend_fn
from .config import Config
from .llm import make_client
from .models import (
    Case,
    Response,
    RunMeta,
    Score,
    config_fingerprint,
    fingerprint,
    rubric_fingerprint,
)
from .report import build_report
from .runner import SQLiteStore
from .runner.runner import Runner, RunnerOptions, run_corpus


# ─── helpers ──────────────────────────────────────────────────────────────


def _is_mock(cfg: Config) -> bool:
    if cfg.mock:
        return True
    from .llm import provider_needs_key

    env = provider_needs_key(cfg.llm.provider, cfg.llm.api_key_env)
    # Local providers (ollama, …) need no key -> run live; key-providers mock if key absent.
    return bool(env) and not os.environ.get(env)


def _client(cfg: Config):
    if _is_mock(cfg):
        return None
    return make_client(
        cfg.model or cfg.analyze.judge_model,
        provider=cfg.llm.provider, base_url=cfg.llm.base_url, api_key_env=cfg.llm.api_key_env,
    )


def _store(cfg: Config) -> SQLiteStore:
    out = Path(cfg.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    return SQLiteStore(out / "polygraph.sqlite")


def _run_dir(cfg: Config, run_id: str) -> Path:
    d = Path(cfg.out_dir).expanduser() / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rubric(cfg: Config):
    path = cfg.resolve(cfg.analyze.rubric)
    return A.load_rubric(path) if path else A.default_rubric()


def _resolve_personas(cfg: Config, client) -> list:
    if cfg.personas_path:
        return P.load_personas_file(cfg.resolve(cfg.personas_path))
    if cfg.audit.personas:
        return P.select(cfg.audit.personas)
    if cfg.audit.tailor_personas and cfg.domain:
        n = cfg.audit.persona_pool or 6
        return asyncio.run(P.generate_panel(client, n, cfg.domain, mock=_is_mock(cfg)))
    return P.sample_pool(cfg.audit.persona_pool or 5, seed=cfg.corpus.seed)


def _build_sample(
    cases: list[Case],
    responses: list[Response],
    scores: list[Score],
    per_category: int,
) -> list[dict]:
    """Curate per-category sample (worst + best by mean dimension score)."""
    by_id_resp = {r.case_id: r for r in responses}
    by_id_score = {s.case_id: s for s in scores}
    by_cat: dict[str, list[Case]] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)

    def mean(score: Score | None) -> float:
        if not score:
            return 0.0
        vals = [v for v in score.dimensions.values() if v is not None]
        return sum(vals) / len(vals) if vals else 0.0

    sample: list[dict] = []
    for cat, cs in by_cat.items():
        graded = [c for c in cs if by_id_resp.get(c.id) and (by_id_resp[c.id].text or "").strip()]
        graded.sort(key=lambda c: mean(by_id_score.get(c.id)))
        pick = graded[: max(1, per_category - 1)] + (graded[-1:] if len(graded) > 1 else [])
        seen = set()
        for c in pick:
            if c.id in seen:
                continue
            seen.add(c.id)
            sc = by_id_score.get(c.id)
            sample.append(
                {
                    "category": cat,
                    "case_id": c.id,
                    "prompt": c.prompt,
                    "response": (by_id_resp[c.id].text if c.id in by_id_resp else ""),
                    "rubric_scores": {k: v for k, v in (sc.dimensions if sc else {}).items() if v is not None},
                    "expected_behavior": c.expected_behavior,
                }
            )
    return sample


def _print_summary(summary: dict) -> None:
    cs = summary.get("category_scores", {})
    dims = summary.get("dimensions", [])
    print(f"\nVerdict: {summary.get('categories_passing')}/{summary.get('categories_total')} "
          f"categories pass (threshold {summary.get('threshold')})  "
          f"overall_pass={summary.get('overall_pass')}")
    header = f"{'category':<18} {'n':>3}  " + "  ".join(f"{d[:8]:>8}" for d in dims) + "  pass"
    print(header)
    print("-" * len(header))
    for cat, sc in cs.items():
        cells = "  ".join(
            (f"{sc.get(d):8.2f}" if isinstance(sc.get(d), (int, float)) else f"{'—':>8}")
            for d in dims
        )
        print(f"{cat:<18} {sc.get('count', 0):>3}  {cells}   {'✓' if sc.get('pass') else '✗'}")
    lat = summary.get("latency", {})
    cost = summary.get("cost", {})
    print(f"\nlatency p50={lat.get('p50_ms')}ms p95={lat.get('p95_ms')}ms  "
          f"tokens in/out={cost.get('tokens_in')}/{cost.get('tokens_out')}  "
          f"assertion_pass_rate={summary.get('assertion_pass_rate')}")


def _save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


# ─── commands ─────────────────────────────────────────────────────────────


def cmd_run(cfg: Config, args) -> RunMeta:
    client = _client(cfg)
    cases = C.build_corpus(cfg.corpus, resolve=cfg.resolve, client=client, mock=_is_mock(cfg), domain=cfg.domain)
    store = _store(cfg)
    adapter = build_adapter(cfg.adapter, **_adapter_extra(args))
    meta = RunMeta(
        name=cfg.name,
        mode=cfg.corpus.mode,
        adapter=adapter.name,
        model=cfg.model,
        total_cases=len(cases),
        corpus_fingerprint=fingerprint(cases),
        config=cfg.model_dump(mode="json"),
        project=os.environ.get("POLYGRAPH_PROJECT") or cfg.name or "default",
        config_fingerprint=config_fingerprint(cfg.model_dump(mode="json")),
        rubric_fingerprint=rubric_fingerprint(_rubric(cfg)),
        sut_git_sha=os.environ.get("POLYGRAPH_SUT_GIT_SHA"),
        sut_ref=os.environ.get("POLYGRAPH_SUT_REF"),
    )
    store.save_run(meta)
    store.save_cases(meta.run_id, cases)
    opts = RunnerOptions(
        concurrency=cfg.run.concurrency,
        rps=cfg.run.rps,
        timeout_s=cfg.run.timeout_s,
        retries=cfg.run.retries,
        resume=cfg.run.resume,
    )
    print(f"run {meta.run_id}: {len(cases)} cases via {adapter.name} (mode={cfg.corpus.mode})")
    responses = asyncio.run(
        run_corpus(adapter, store, meta.run_id, cases, opts, adapter_sig=cfg.adapter.options)
    )
    ok = sum(1 for r in responses if not r.error)
    meta.completed_cases = ok
    meta.completed_at = RunMeta().created_at
    store.save_run(meta)
    print(f"done: {ok}/{len(cases)} responses ok")
    return meta


def _adapter_extra(args) -> dict:
    """Allow a Python callable adapter to be injected via --callable module:fn."""
    spec = getattr(args, "callable", None)
    if not spec:
        return {}
    mod, _, fn = spec.partition(":")
    import importlib

    return {"fn": getattr(importlib.import_module(mod), fn)}


def cmd_generate(cfg: Config, args) -> None:
    import sys

    client = _client(cfg)
    _gen_state = {"target": 0}

    def _prog(stage: str, info: dict) -> None:
        if stage == "plan":
            _gen_state["target"] = info.get("target", 0)
            print(_color(f"planning {_gen_state['target']} prompts (mode={info.get('mode')})…", "dim"))
        elif stage == "batch":
            sys.stdout.write(_color(f"\r  batch {info.get('index')} (+{info.get('size')})…", "dim"))
            sys.stdout.flush()
        elif stage == "prompt":
            t = info.get("target") or _gen_state["target"] or "?"
            sys.stdout.write(f"\r  generated {info.get('i')}/{t}  ({(info.get('category') or '')[:24]})            ")
            sys.stdout.flush()
        elif stage == "done":
            sys.stdout.write("\n")
            sys.stdout.flush()

    cases = C.build_corpus(cfg.corpus, resolve=cfg.resolve, client=client,
                           mock=_is_mock(cfg), domain=cfg.domain, progress=_prog)
    out = Path(args.out or (Path(cfg.out_dir) / "generated")).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    by_cat: dict[str, list[dict]] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c.model_dump(mode="json"))
    for cat, rows in by_cat.items():
        (out / f"{cat}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"generated {len(cases)} cases across {len(by_cat)} categories -> {out}")


def cmd_analyze(cfg: Config, run_id: str) -> dict:
    store = _store(cfg)
    cases = store.get_cases(run_id)
    responses = store.get_responses(run_id)
    rubric = _rubric(cfg)
    client = _client(cfg)
    scores = asyncio.run(
        A.analyze_run(
            cases, responses, rubric,
            client=client, judges=cfg.analyze.judges, model=cfg.analyze.judge_model or cfg.model,
            temperature=cfg.analyze.temperature, mock=_is_mock(cfg), config=cfg,
        )
    )
    for s in scores:
        store.save_score(run_id, s)
    summary = A.summarize(cases, responses, scores, rubric, config=cfg)
    _save_json(_run_dir(cfg, run_id) / "summary.json", summary)
    store.export_jsonl(run_id, _run_dir(cfg, run_id) / "cases.jsonl")
    _print_summary(summary)
    return summary


def _resolve_baseline_summary(cfg: Config, store, run_id: str, spec: str):
    """Resolve a baseline spec into a (summary, label). Spec is a run id,
    ``rolling:N`` (median of the N most-recent comparable runs), or ``HEAD``
    (the most-recent comparable run before this one)."""
    spec = (spec or "").strip()
    meta = store.get_run(run_id)
    fp = meta.corpus_fingerprint if meta else None

    def _comparable_prior():
        prior = [m for m in store.list_runs()
                 if m.run_id != run_id and (fp is None or m.corpus_fingerprint == fp)]
        prior.sort(key=lambda m: m.created_at or "", reverse=True)
        return prior

    if spec.startswith("rolling:"):
        n = int(spec.split(":", 1)[1] or "5")
        summaries = []
        for m in _comparable_prior()[:n]:
            p = _run_dir(cfg, m.run_id) / "summary.json"
            if p.exists():
                summaries.append(json.loads(p.read_text()))
        return A.rolling_baseline_summary(summaries), f"rolling:{len(summaries)}"
    if spec.upper() == "HEAD":
        prior = _comparable_prior()
        if not prior:
            return {}, "HEAD(none)"
        p = _run_dir(cfg, prior[0].run_id) / "summary.json"
        return (json.loads(p.read_text()) if p.exists() else {}), prior[0].run_id[:8]
    # explicit run id
    p = _run_dir(cfg, spec) / "summary.json"
    return (json.loads(p.read_text()) if p.exists() else {}), spec[:8]


def _ci_feedback(cfg: Config, args, summary: dict) -> None:
    """Emit GitHub annotations / a PR-comment / a job summary for an analyze --ci
    run, computing the baseline diff when --baseline is given."""
    from . import ci as _ci

    baseline_diff = None
    spec = getattr(args, "baseline", None)
    if spec:
        store = _store(cfg)
        baseline, label = _resolve_baseline_summary(cfg, store, args.run, spec)
        if baseline:
            alpha = float(getattr(cfg.analyze, "alpha", 0.05) or 0.05)
            conf = float(getattr(cfg.analyze, "confidence", 0.95) or 0.95)
            baseline_diff = A.diff_baseline(summary, baseline, alpha=alpha, confidence=conf)
            _save_json(_run_dir(cfg, args.run) / "ci_baseline_diff.json", baseline_diff)
            print(_color(f"baseline {label}: {len(baseline_diff['regressions'])} regression(s), "
                         f"{len(baseline_diff.get('significant_regressions', []))} significant", "dim"))

    if getattr(args, "github_annotations", False):
        n = _ci.emit_annotations(summary, baseline_diff)
        md = _ci.pr_comment_markdown(summary, baseline_diff, run_id=args.run)
        if _ci.write_step_summary(md):
            print(_color("wrote GitHub job summary", "dim"))
        print(_color(f"emitted {n} annotation(s)", "dim"))

    if getattr(args, "pr_comment", None):
        md = _ci.pr_comment_markdown(summary, baseline_diff, run_id=args.run)
        Path(args.pr_comment).write_text(md)
        print(f"  pr-comment: {args.pr_comment}")


def cmd_audit(cfg: Config, run_id: str) -> dict:
    store = _store(cfg)
    cases = store.get_cases(run_id)
    responses = store.get_responses(run_id)
    scores = store.get_scores(run_id)
    rubric = _rubric(cfg)
    client = _client(cfg)
    personas = _resolve_personas(cfg, client)
    sample = _build_sample(cases, responses, scores, cfg.audit.sample_per_category)
    audit = asyncio.run(
        AU.run_audit(
            cases, responses, scores, rubric, personas, sample,
            client=client, code_path=cfg.resolve(cfg.audit.code_path),
            forensic=cfg.audit.forensic, mock=_is_mock(cfg),
        )
    )
    _save_json(_run_dir(cfg, run_id) / "audit.json", audit)
    fr = audit.get("forensic", {}).get("synthesis", {})
    print(f"audit: {len(personas)} personas, "
          f"{len(audit.get('forensic', {}).get('category_audits', []))} category audits")
    if fr.get("narrative"):
        print(f"  → {fr['narrative'][:200]}")
    return audit


def cmd_report(cfg: Config, run_id: str, formats: list[str], baseline_id: str | None = None) -> dict:
    store = _store(cfg)
    meta = store.get_run(run_id)
    cases = store.get_cases(run_id)
    responses = store.get_responses(run_id)
    scores = store.get_scores(run_id)
    rubric = _rubric(cfg)
    rd = _run_dir(cfg, run_id)
    summary_path = rd / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else A.summarize(cases, responses, scores, rubric, config=cfg)
    audit_path = rd / "audit.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
    baseline_diff = None
    if baseline_id:
        bpath = _run_dir(cfg, baseline_id) / "summary.json"
        if bpath.exists():
            baseline_diff = A.diff_baseline(summary, json.loads(bpath.read_text()))
    paths = build_report(
        meta, cases, responses, scores, summary,
        rubric=rubric, audit=audit, baseline_diff=baseline_diff,
        formats=formats, out_dir=str(rd),
        template=cfg.report.template, template_dir=cfg.resolve(cfg.report.template_dir),
        branding=cfg.report.branding,
    )
    for fmt, p in paths.items():
        print(f"  {fmt}: {p}")
    if "pdf" not in paths and "pdf" in formats:
        print("  pdf: skipped (no libreoffice/reportlab available)")
    return paths


def cmd_compare(cfg: Config, args) -> dict:
    store = _store(cfg)

    # N-run mode (--runs id1,id2,...) takes precedence; falls back to --run-a/--run-b.
    run_list = [r.strip() for r in args.runs.split(",") if r.strip()] if getattr(args, "runs", None) else []
    if not run_list and getattr(args, "run_a", None) and getattr(args, "run_b", None):
        run_list = [args.run_a, args.run_b]
    if len(run_list) < 2:
        raise SystemExit("compare requires --runs id1,id2[,...] or --run-a and --run-b")

    report = compare_runs_fn(
        store, run_list, cfg.out_dir, baseline_run_id=getattr(args, "baseline", None)
    )

    # Write the ComparisonReport against the chronologically-latest run dir.
    latest = report["run_ids"][-1]
    suffix = "_".join(r[:8] for r in report["run_ids"])
    _save_json(_run_dir(cfg, latest) / f"comparison_{suffix}.json", report)

    ov = report["overall"]
    if "wins_a" in ov:
        a, b = report["run_ids"]
        print(f"A/B {a[:8]} vs {b[:8]}: wins_a={ov['wins_a']} wins_b={ov['wins_b']} ties={ov['ties']}")
    else:
        print(f"compared {len(report['run_ids'])} runs ({report['comparability']}):")
        for row in ov["per_run"]:
            print(f"  {row['run_id'][:8]}  pass={row['overall_pass']}  "
                  f"{row['categories_passing']}/{row['categories_total']} categories")
    print(f"regressions={len(report['regressions'])}  improvements={len(report['improvements'])}")
    return report


def cmd_trend(cfg: Config, args) -> list:
    store = _store(cfg)
    blocks = trend_fn(
        store,
        project=getattr(args, "project", None),
        out_dir=cfg.out_dir,
        window=getattr(args, "window", 30) or 30,
    )
    out = Path(cfg.out_dir).expanduser() / "trend.json"
    _save_json(out, blocks)
    print(f"trend over project={args.project or '(latest corpus)'} window={args.window}: "
          f"{len(blocks)} categories -> {out}")
    for blk in blocks:
        for dim in blk["dimensions"]:
            slope = dim["slope"]
            if slope is None:
                continue
            arrow = "↑" if slope > 0 else ("↓" if slope < 0 else "→")
            print(f"  {blk['category']:<18} {dim['dimension']:<12} slope={slope:+.3f}/run {arrow}")
    return blocks


def cmd_regressions(cfg: Config, args) -> dict:
    store = _store(cfg)
    rd = _run_dir(cfg, args.run)
    cur_path = rd / "summary.json"
    if cur_path.exists():
        current = json.loads(cur_path.read_text())
    else:
        cases = store.get_cases(args.run)
        current = A.summarize(cases, store.get_responses(args.run), store.get_scores(args.run), _rubric(cfg), config=cfg)

    against = args.against
    if against.startswith("rolling:"):
        n = int(against.split(":", 1)[1] or "5")
        meta = store.get_run(args.run)
        fp = meta.corpus_fingerprint if meta else None
        # Most recent comparable runs strictly before `args.run`, newest-first.
        prior = [
            m for m in store.list_runs()
            if m.run_id != args.run and (fp is None or m.corpus_fingerprint == fp)
        ]
        prior.sort(key=lambda m: m.created_at or "", reverse=True)
        window = prior[:n]
        summaries = []
        for m in window:
            p = _run_dir(cfg, m.run_id) / "summary.json"
            if p.exists():
                summaries.append(json.loads(p.read_text()))
        baseline = A.rolling_baseline_summary(summaries)
        label = f"rolling:{len(summaries)}"
    else:
        bpath = _run_dir(cfg, against) / "summary.json"
        baseline = json.loads(bpath.read_text()) if bpath.exists() else {}
        label = against[:8]

    alpha = float(getattr(cfg.analyze, "alpha", 0.05) or 0.05)
    confidence = float(getattr(cfg.analyze, "confidence", 0.95) or 0.95)
    diff = A.diff_baseline(current, baseline, alpha=alpha, confidence=confidence)
    out = rd / f"regressions_vs_{label.replace(':', '_')}.json"
    _save_json(out, diff)
    sig = diff.get("significance", {}) or {}
    sig_note = ""
    if sig.get("available"):
        sig_note = (f"; {len(diff['significant_regressions'])} statistically significant "
                    f"(BH α={sig.get('alpha')})")
    print(f"regressions {args.run[:8]} vs {label}: "
          f"{len(diff['regressions'])} regressions, {len(diff['improvements'])} improvements"
          f"{sig_note} -> {out}")
    for r in diff["regressions"]:
        star = ""
        for s in diff.get("significant_regressions", []):
            if s["category"] == r["category"] and s["dimension"] == r["dimension"]:
                star = f"  [significant, q={s.get('q_value'):.3f}]"
                break
        print(f"  ↓ {r['category']}/{r['dimension']}: {r['baseline']:.2f} -> {r['current']:.2f} "
              f"({r['delta']:+.2f}){star}")
    return diff


def cmd_personas(cfg: Config, args) -> None:
    if args.persona_cmd == "list":
        for p in P.load_library():
            print(f"{p.id:<26} {p.who[:90]}")
    elif args.persona_cmd == "new":
        client = _client(cfg)
        persona = asyncio.run(P.create_persona(client, args.description, mock=_is_mock(cfg)))
        out = Path(args.out or f"{persona.id}.yaml").expanduser()
        import yaml

        out.write_text(yaml.safe_dump(persona.model_dump(), sort_keys=False))
        print(f"created persona '{persona.id}' -> {out}")
    elif args.persona_cmd == "generate":
        client = _client(cfg)
        panel = asyncio.run(P.generate_panel(client, args.count, args.domain, mock=_is_mock(cfg)))
        out = Path(args.out or "personas.yaml").expanduser()
        import yaml

        out.write_text(yaml.safe_dump([p.model_dump() for p in panel], sort_keys=False))
        print(f"generated {len(panel)} personas -> {out}")


def cmd_init(cfg: Config, args) -> int:
    """Detect usable providers/models and scaffold a config. The Studio + Arena
    dropdowns read the same detection, so this is the proper setup step."""
    from .discovery import discover_providers

    provs = discover_providers()
    print(_color("PromptPolygraph setup — providers detected:", "bold"))
    available = []
    for p in provs:
        mark = _color("✓", "green") if p["available"] else _color("·", "dim")
        print(f"  {mark} {p['label']:<22} {p['reason']}")
        if p["available"]:
            print(_color(f"      models: {', '.join(p.get('models') or []) or '—'}", "dim"))
            available.append(p)

    if available:
        print(_color("\nstatus: ● ready — runs live on a configured provider", "green"))
    else:
        print(_color("\nstatus: ● mock-only — set a key or start Ollama to run live", "yellow"))

    print(_color("target (system under test):", "bold"))
    print("  configure `adapter:` in your config — type: demo (offline sample) | llm (a model) | "
          "http (a web API) | callable (your own module:function for a custom integration).")
    print(_color("  the dashboard's New-run screen has a 'Test connection' button to verify it (green = good to go).", "dim"))

    default = available[0] if available else None
    out = Path(args.out or "promptpolygraph.yaml").expanduser()
    if out.exists() and not args.force:
        print(_color(f"\n{out} exists (use --force to overwrite). Detection above is current.", "yellow"))
        return 0

    backend: dict[str, Any] = {"provider": default["id"] if default else "ollama"}
    if default and default.get("base_url"):
        backend["base_url"] = default["base_url"]
    data: dict[str, Any] = {
        "name": "polygraph-run",
        "llm": backend,
        "model": default["default_model"] if default else None,
        "redteam": {"profile": "all_frontier"},
    }
    import yaml

    out.write_text(yaml.safe_dump(data, sort_keys=False))
    print(_color(f"\nwrote {out}", "green"))
    if not available:
        print("no providers usable yet — set ANTHROPIC_API_KEY / OPENAI_API_KEY, "
              "or run `ollama serve` and `ollama pull llama3.1`.")
    print("next: polygraph dashboard   (the Studio + Arena read these providers for their dropdowns)")
    return 0


def cmd_dashboard(cfg: Config, args) -> None:
    from .ui import serve_dashboard

    serve_dashboard(
        out_dir=cfg.out_dir,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )


def cmd_export(cfg: Config, args) -> None:
    """Export the prompts/corpus of a run (or any corpus dir) as a reusable dataset."""
    import csv

    if args.run:
        cases = _store(cfg).get_cases(args.run)
        src = f"run {args.run[:8]}"
    elif args.corpus:
        from . import corpus as C

        cases = C.load_corpus(cfg.resolve(args.corpus) or args.corpus)
        src = f"corpus {args.corpus}"
    else:
        raise SystemExit("export requires --run <id> or --corpus <path>")

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = args.format

    if args.prompts_only:
        rows: list[Any] = [{"prompt": c.prompt, "category": c.category} for c in cases]
    else:
        rows = [c.model_dump(mode="json", exclude={"id"}) for c in cases]

    if fmt == "json":
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    elif fmt == "jsonl":
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    elif fmt == "csv":
        cols = ["prompt", "category", "subcategory", "expected_shape", "expected_behavior"]
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for c in cases:
                w.writerow({"prompt": c.prompt, "category": c.category,
                            "subcategory": c.subcategory or "", "expected_shape": c.expected_shape or "",
                            "expected_behavior": c.expected_behavior or ""})
    else:
        raise SystemExit(f"unknown format: {fmt}")
    print(f"exported {len(cases)} prompts from {src} -> {out} ({fmt})")


def cmd_elicit(cfg: Config, args) -> None:
    from . import elicit as E

    client = _client(cfg)
    mock = _is_mock(cfg)
    sub = args.elicit_cmd

    if sub in ("init", "interview"):
        suggested = asyncio.run(E.suggest_brief(client, args.domain, mock=mock))
        if sub == "interview":
            brief = E.interview(args.domain, suggested)
        else:
            brief = E.brief_template(args.domain, suggested)
        out = args.out or "brief.yaml"
        E.write_brief(out, brief)
        print(f"wrote domain brief -> {out}")
        print("Edit it with your SME, then: "
              f"polygraph elicit build --brief {out} --out <project_dir>")

    elif sub == "build":
        brief = E.load_brief(args.brief)
        result = asyncio.run(
            E.build_from_brief(brief, args.out, per_category=args.per_category, client=client, mock=mock)
        )
        print(f"drafted {result['drafted']} probes across {len(result['categories'])} categories -> {result['dir']}")
        print(f"  rubric dims: {', '.join(result['dimensions'])}  |  personas: {result['personas']}")
        print(f"\nReview/edit {result['review']} (set decision: reject to drop a probe), then:")
        print(f"  polygraph elicit finalize --review {result['review']} --out {result['dir']}")

    elif sub == "finalize":
        result = E.finalize(args.review, args.out)
        print(f"golden corpus written: {result['kept']} probes kept, {result['dropped']} dropped "
              f"-> {result['corpus']}")
        print(f"\nrun it:  polygraph all --config {Path(result['dir']) / 'config.yaml'} --mock")


def cmd_tune(cfg: Config, args) -> None:
    from . import tune as T

    client = _client(cfg)
    cats = args.categories.split(",") if args.categories else None
    result = asyncio.run(
        T.scaffold(
            args.domain, args.out,
            categories=cats, count=args.count, n_personas=args.personas,
            adapter_type=args.adapter, client=client, mock=_is_mock(cfg),
        )
    )
    print(f"scaffolded tailored project -> {result['dir']}")
    print(f"  rubric dimensions: {', '.join(result['dimensions'])}")
    print(f"  personas: {result['personas_count']}  |  corpus: {result['cases']} cases "
          f"across {len(result['categories'])} categories")
    print(f"\nrun it:  polygraph all --config {result['config']} --mock --format md,html")


# ─── redteam ──────────────────────────────────────────────────────────────

_ANSI = {
    "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m",
    "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m",
}


def _color(text: str, name: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{_ANSI.get(name, '')}{text}{_ANSI['reset']}"


def _trunc(text: str | None, n: int = 90) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


_SEV_COLOR = {"critical": "red", "high": "red", "medium": "yellow", "low": "yellow", "none": "green"}


def _redteam_printer():
    """A sync emit callback that prints a live console feed of the run."""
    names: dict[str, str] = {}

    def emit(ev) -> None:
        t = ev.type
        if t == "profile":
            d = ev.data or {}
            print(_color(f"red team '{d.get('name')}' vs {d.get('target')} "
                         f"({len(d.get('attackers') or [])} agents, turns={d.get('turns')})", "bold"))
        elif t == "agent_spawned":
            d = ev.data or {}
            label = f"{ev.strategy}@{d.get('provider')}/{d.get('model')}"
            names[ev.attacker_id or ""] = ev.strategy or ""
            print(_color(f"  + agent {ev.attacker_id} {label} [{d.get('intensity')}]", "dim"))
        elif t == "attack":
            print(f"  → [{ev.attacker_id} {ev.strategy} t{ev.turn}] {_trunc(ev.text)}")
        elif t == "verdict":
            v = ev.verdict or {}
            if v.get("breached"):
                sev = v.get("severity", "?")
                msg = _color(f"    ✗ BREACH {sev} ({v.get('vuln_class')})", _SEV_COLOR.get(sev, "red"))
            else:
                msg = _color("    ✓ defended", "green")
            print(msg)
        elif t == "summary":
            d = ev.data or {}
            print(_color(f"\nsummary: {d.get('breaches')}/{d.get('attacks')} breached, "
                         f"{d.get('defended')} defended", "bold"))

    return emit


def cmd_redteam(cfg: Config, args) -> int:
    from .redteam import get_profile, run_redteam
    from .redteam.report import render_html, render_json, render_md
    from .redteam.models import severity_rank

    prof = get_profile(args.profile or cfg.redteam.profile)
    if getattr(args, "turns", None) is not None:
        prof.turns = args.turns
    elif cfg.redteam.turns is not None:
        prof.turns = cfg.redteam.turns
    prof.target_description = cfg.redteam.target_description or cfg.domain
    if getattr(args, "guard", False):
        prof.judge_kind = "llama_guard"

    sources = (
        [s.strip() for s in args.sources.split(",") if s.strip()]
        if getattr(args, "sources", None) is not None
        else list(cfg.redteam.sources)
    )

    try:
        adapter = build_adapter(cfg.adapter)
    except Exception:
        # zero-config demo: fall back to the offline demo target (mirrors the Arena)
        from .adapters import DemoAdapter
        adapter = DemoAdapter(name="demo", style="everyday")
    print(_color(f"redteam: profile={prof.name} target={adapter.name} "
                 f"mock={_is_mock(cfg)}" + (f" sources={','.join(sources)}" if sources else ""), "dim"))

    report = asyncio.run(
        run_redteam(
            adapter, prof, emit=_redteam_printer(),
            mock=_is_mock(cfg), concurrency=cfg.redteam.concurrency,
            extra_sources=sources, source_count=cfg.redteam.source_count,
        )
    )

    rd = _run_dir(cfg, report.run_id)
    formats = [f.strip() for f in (args.format or "md").split(",") if f.strip()]
    written: list[Path] = []
    if "md" in formats:
        p = rd / "redteam.md"
        p.write_text(render_md(report))
        written.append(p)
    if "html" in formats:
        p = rd / "redteam.html"
        p.write_text(render_html(report))
        written.append(p)
    if "json" in formats:
        p = rd / "redteam.json"
        _save_json(p, render_json(report))
        written.append(p)
    if "junit" in formats:
        from .report.junit import render_junit_redteam
        p = rd / "redteam.junit.xml"
        p.write_text(render_junit_redteam(report))
        written.append(p)
    if "sarif" in formats:
        from .report.sarif import render_sarif_redteam
        p = rd / "redteam.sarif.json"
        p.write_text(render_sarif_redteam(report))
        written.append(p)
    # always keep a machine-readable copy
    if "json" not in formats:
        _save_json(rd / "redteam.json", render_json(report))
    # provenance manifest: what produced this result (sources+versions, pinned mapping)
    from . import provenance as P
    _save_json(rd / "provenance.json", P.redteam_provenance(report, sources=sources))

    st = report.stats or {}
    print(_color(f"\nverdict: {st.get('breaches', 0)}/{st.get('attacks', 0)} attacks breached "
                 f"({st.get('defended', 0)} defended)", "bold"))
    if report.vulnerabilities:
        print("top vulnerabilities:")
        for v in report.vulnerabilities[:5]:
            print(f"  {_color(v.severity.upper(), _SEV_COLOR.get(v.severity, 'red'))} "
                  f"{v.vuln_class} ×{v.count} — {_trunc(v.mitigation, 80)}")
    else:
        print(_color("no vulnerabilities — target defended every probe", "green"))
    for p in written:
        print(f"  report: {p}")

    worst = max((severity_rank(v.severity) for v in report.vulnerabilities), default=0)
    return 1 if worst >= severity_rank("high") else 0


def cmd_redteam_profiles(cfg: Config, args) -> None:
    from .redteam import get_profile, list_profiles

    for name in list_profiles():
        prof = get_profile(name)
        backends = sorted({f"{a.provider}/{a.model}" for a in prof.attackers})
        print(f"{name:<14} {len(prof.attackers)} agents, turns={prof.turns}  "
              f"[{', '.join(backends)}]")
        print(f"  {_color(prof.description, 'dim')}")


def cmd_all(cfg: Config, args) -> int:
    meta = cmd_run(cfg, args)
    summary = cmd_analyze(cfg, meta.run_id)
    if cfg.audit.enabled:
        cmd_audit(cfg, meta.run_id)
    cmd_report(cfg, meta.run_id, args.format.split(","))
    print(f"\nrun_id: {meta.run_id}")
    return A.ci_exit_code(summary)


# ─── argparse ─────────────────────────────────────────────────────────────


def _load_cfg(args) -> Config:
    cfg = Config.load(args.config) if args.config else Config()
    if getattr(args, "mock", False):
        cfg.mock = True
    if getattr(args, "out_dir", None):
        cfg.out_dir = args.out_dir
    if getattr(args, "mode", None):
        cfg.corpus.mode = args.mode
    if getattr(args, "count", None) is not None:
        cfg.corpus.count = args.count
    if getattr(args, "per_category", None) is not None:
        cfg.corpus.per_category = args.per_category
    if getattr(args, "categories", None):
        cfg.corpus.categories = args.categories.split(",")
    if getattr(args, "difficulty", None):
        cfg.corpus.difficulty = args.difficulty
    if getattr(args, "domain", None):
        cfg.domain = args.domain
    if getattr(args, "concurrency", None) is not None:
        cfg.run.concurrency = args.concurrency
    if getattr(args, "judges", None) is not None:
        cfg.analyze.judges = args.judges
    return cfg


def _add_corpus_dials(p: argparse.ArgumentParser) -> None:
    p.add_argument("--mode", choices=["fixed", "varied", "adversarial", "hybrid"],
                   help="fixed: load a saved set (reproducible) · varied: LLM-generate fresh prompts · "
                        "adversarial: red-team/edge prompts · hybrid: fixed core + generated supplement")
    p.add_argument("--count", type=int, help="total prompts to generate (alternative to --per-category)")
    p.add_argument("--per-category", dest="per_category", type=int,
                   help="prompts per category (varied/adversarial)")
    p.add_argument("--categories", help="comma-separated category names to cover")
    p.add_argument("--difficulty", choices=["mild", "standard", "aggressive"],
                   help="adversarial pressure level for generated probes")
    p.add_argument("--concurrency", type=int, help="parallel in-flight requests to the target")
    p.add_argument("--seed", type=int,
                   help="fix the RNG so 'varied' generation is reproducible (same seed => same prompts); "
                        "omit for fresh prompts each run")
    p.add_argument("--domain", help="one-line description of the system under test; tailors generated prompts")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polygraph", description=__doc__.split("\n")[0])
    # Common options live on a parent so they work in either position
    # (e.g. `polygraph --mock all ...` and `polygraph all --mock ...`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="path to a config.yaml")
    common.add_argument("--out-dir", dest="out_dir", help="output directory")
    common.add_argument("--mock", action="store_true", help="offline deterministic mode (no API calls)")
    parser.add_argument("--config", help=argparse.SUPPRESS)
    parser.add_argument("--out-dir", dest="out_dir", help=argparse.SUPPRESS)
    parser.add_argument("--mock", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", parents=[common], help="query the target across the corpus")
    _add_corpus_dials(pr)
    pr.add_argument("--callable", help="module:function to use as an in-process adapter")

    pg = sub.add_parser("generate", parents=[common], help="synthesize a corpus to files")
    _add_corpus_dials(pg)
    pg.add_argument("--out", help="output directory for generated corpus")

    pa = sub.add_parser("analyze", parents=[common], help="score a run")
    pa.add_argument("--run", required=True)
    pa.add_argument("--judges", type=int)
    pa.add_argument("--ci", action="store_true", help="exit non-zero if the gate fails")
    pa.add_argument("--baseline", help="baseline for regression check: a run id, rolling:N, or HEAD")
    pa.add_argument("--github-annotations", action="store_true",
                    help="emit GitHub Actions ::error/::warning annotations + job summary")
    pa.add_argument("--pr-comment", dest="pr_comment", metavar="PATH",
                    help="write a markdown PR-comment summary to this path")

    pu = sub.add_parser("audit", parents=[common], help="persona + forensic audit of a run")
    pu.add_argument("--run", required=True)

    prp = sub.add_parser("report", parents=[common], help="render a report")
    prp.add_argument("--run", required=True)
    prp.add_argument("--format", default="md,html",
                     help="comma list: md,html,docx,pdf,junit,sarif (junit/sarif for CI)")
    prp.add_argument("--baseline", help="prior run id for delta columns")

    pc = sub.add_parser("compare", parents=[common], help="compare N runs (A/B or trend matrix)")
    pc.add_argument("--run-a", dest="run_a", help="first run (A/B mode)")
    pc.add_argument("--run-b", dest="run_b", help="second run (A/B mode)")
    pc.add_argument("--runs", help="comma-separated run ids for an N-run comparison")
    pc.add_argument("--baseline", help="baseline run id for regression/delta classification")

    ptr = sub.add_parser("trend", parents=[common], help="longitudinal trend over a project's runs")
    ptr.add_argument("--project", help="project to trend (default: latest corpus)")
    ptr.add_argument("--window", type=int, default=30, help="most-recent runs to include")

    prg = sub.add_parser("regressions", parents=[common], help="regressions of a run vs a baseline")
    prg.add_argument("--run", required=True, help="run to evaluate")
    prg.add_argument("--against", required=True, help="baseline run id, or 'rolling:N'")

    pp = sub.add_parser("personas", parents=[common], help="manage personas")
    psub = pp.add_subparsers(dest="persona_cmd", required=True)
    psub.add_parser("list", parents=[common])
    pnew = psub.add_parser("new", parents=[common])
    pnew.add_argument("description")
    pnew.add_argument("--out")
    pgen = psub.add_parser("generate", parents=[common])
    pgen.add_argument("--count", type=int, default=8)
    pgen.add_argument("--domain", required=True)
    pgen.add_argument("--out")

    pd = sub.add_parser("dashboard", parents=[common], help="launch a local web UI to browse runs (no deps)")
    pd.add_argument("--host", default="127.0.0.1")
    pd.add_argument("--port", type=int, default=8765)
    pd.add_argument("--no-open", dest="no_open", action="store_true", help="don't open a browser")

    pin = sub.add_parser("init", parents=[common], help="detect providers/models and scaffold a config")
    pin.add_argument("--out", help="config file to write (default: promptpolygraph.yaml)")
    pin.add_argument("--force", action="store_true", help="overwrite an existing config")

    px = sub.add_parser("export", parents=[common], help="export a run's / corpus's prompts as a reusable dataset")
    px.add_argument("--run", help="export the prompts of a stored run id")
    px.add_argument("--corpus", help="export the prompts of a corpus dir/file")
    px.add_argument("--out", required=True, help="output file")
    px.add_argument("--format", default="json", choices=["json", "jsonl", "csv"])
    px.add_argument("--prompts-only", dest="prompts_only", action="store_true",
                    help="export just prompt + category (a clean prompt corpus)")

    pe = sub.add_parser("elicit", parents=[common], help="bootstrap an expert-validated golden probe set")
    esub = pe.add_subparsers(dest="elicit_cmd", required=True)
    ei = esub.add_parser("init", parents=[common], help="write a domain brief template")
    ei.add_argument("--domain", required=True)
    ei.add_argument("--out", help="brief output path (default brief.yaml)")
    ev = esub.add_parser("interview", parents=[common], help="interactive SME walkthrough -> brief")
    ev.add_argument("--domain", required=True)
    ev.add_argument("--out", help="brief output path (default brief.yaml)")
    eb = esub.add_parser("build", parents=[common], help="brief -> draft probes + review sheet")
    eb.add_argument("--brief", required=True)
    eb.add_argument("--out", required=True, help="project directory")
    eb.add_argument("--per-category", dest="per_category", type=int, default=6)
    ef = esub.add_parser("finalize", parents=[common], help="reviewed sheet -> golden corpus")
    ef.add_argument("--review", required=True)
    ef.add_argument("--out", required=True, help="project directory")

    pt = sub.add_parser("tune", parents=[common], help="scaffold a tailored project for a domain")
    pt.add_argument("--domain", required=True, help="one-line description of the system under test")
    pt.add_argument("--out", required=True, help="output project directory")
    pt.add_argument("--categories", help="comma-separated category names")
    pt.add_argument("--count", type=int, default=40, help="starter corpus size")
    pt.add_argument("--personas", type=int, default=8, help="persona panel size")
    pt.add_argument("--adapter", default="demo", choices=["demo", "http", "llm", "callable"])

    prt = sub.add_parser("redteam", parents=[common],
                         help="authorized adversarial red-team of the target -> vuln report")
    rtsub = prt.add_subparsers(dest="redteam_cmd")
    rtsub.add_parser("profiles", parents=[common], help="list built-in red-team profiles")
    prt.add_argument("--profile", help="built-in profile name (default: cfg.redteam.profile)")
    prt.add_argument("--turns", type=int, help="override escalation depth per attacker")
    prt.add_argument("--sources", help="comma-separated OSS probe sources to fold in "
                                       "(e.g. catalog,garak,pyrit,dataset:advbench)")
    prt.add_argument("--guard", action="store_true",
                     help="judge breaches with a Llama-Guard-style safety classifier instead of the LLM reviewer")
    prt.add_argument("--format", default="md,html", help="md,html,json,junit,sarif")

    pall = sub.add_parser("all", parents=[common], help="run -> analyze -> audit -> report")
    _add_corpus_dials(pall)
    pall.add_argument("--callable", help="module:function in-process adapter")
    pall.add_argument("--judges", type=int)
    pall.add_argument("--format", default="md,html")

    pvc = sub.add_parser("validate-config", parents=[common],
                         help="fail-fast validation of a config (and optional rubric) before a run")
    pvc.add_argument("--rubric", help="also validate this rubric.yaml")

    psc = sub.add_parser("schema", parents=[common],
                         help="write JSON Schemas for config + rubric (editor autocomplete / CI)")
    psc.add_argument("--out", default="schemas", help="output directory (default: schemas/)")

    pmf = sub.add_parser("manifest", parents=[common],
                         help="write a provenance manifest for a run (what produced the result)")
    pmf.add_argument("--run", required=True)

    pcal = sub.add_parser("calibrate", parents=[common],
                          help="score the breach judge against the labeled ground-truth set")
    pcal.add_argument("--guard", action="store_true", help="calibrate the Llama-Guard judge instead")
    pcal.add_argument("--ground-truth", dest="ground_truth", help="path to a custom ground-truth JSON")
    pcal.add_argument("--out", help="write the calibration report JSON here")
    pcal.add_argument("--min-f1", dest="min_f1", type=float,
                      help="exit non-zero if the judge's F1 is below this (CI calibration gate)")

    pref = sub.add_parser("references", parents=[common],
                          help="check or update the pinned OWASP/ATLAS technique mapping")
    pref.add_argument("--check", action="store_true", help="fail if the live mapping drifted from the lock")
    pref.add_argument("--write", action="store_true", help="rewrite the reference lock from the current mapping")

    from .scaffold import providers as _ci_providers
    psci = sub.add_parser("scaffold-ci", parents=[common],
                          help="write a starter CI pipeline (gate + JUnit/SARIF + PR feedback)")
    psci.add_argument("provider", choices=_ci_providers(),
                      help="github | gitlab | jenkins | precommit")
    psci.add_argument("--config-path", dest="config_path", default="config.yaml",
                      help="config path the generated pipeline references")
    psci.add_argument("--force", action="store_true", help="overwrite an existing file")

    return parser


def cmd_validate_config(cfg: Config, args) -> int:
    """Validate a config (and optional rubric) before a run. Exit 1 on any error."""
    from .schema_gen import validate_config_file, validate_rubric_file

    if not args.config:
        print(_color("validate-config: pass --config <path>", "red"))
        return 1
    ok = True
    res = validate_config_file(args.config)
    for w in res["warnings"]:
        print(_color(f"  warning: {w}", "yellow"))
    if res["ok"]:
        print(_color(f"config OK: {args.config}", "green"))
    else:
        ok = False
        print(_color(f"config INVALID: {args.config}", "red"))
        for e in res["errors"]:
            print(f"  ✗ {e}")
    if getattr(args, "rubric", None):
        rres = validate_rubric_file(args.rubric)
        if rres["ok"]:
            print(_color(f"rubric OK: {args.rubric}", "green"))
        else:
            ok = False
            print(_color(f"rubric INVALID: {args.rubric}", "red"))
            for e in rres["errors"]:
                print(f"  ✗ {e}")
    return 0 if ok else 1


def cmd_calibrate(cfg: Config, args) -> int:
    from .calibrate import calibrate_breach_judge, load_ground_truth

    gt = load_ground_truth(args.ground_truth) if getattr(args, "ground_truth", None) else None
    report = asyncio.run(calibrate_breach_judge(
        _client(cfg), mock=_is_mock(cfg), guard=getattr(args, "guard", False),
        ground_truth=gt,
    ))
    out = Path(args.out) if getattr(args, "out", None) else _run_dir(cfg, "calibration") / "calibration.json"
    _save_json(out, report)
    m = report["metrics"]
    verdict = _color("RELIABLE", "green") if report["reliable"] else _color("UNRELIABLE", "red")
    src = "mock judge" if report["mock"] else f"{report['judge']} judge"
    print(f"calibration ({src}, n={report['n']}): {verdict}")
    print(f"  precision={m['precision']:.2f} recall={m['recall']:.2f} f1={m['f1']:.2f} "
          f"accuracy={m['accuracy']:.2f}")
    print(f"  confusion: tp={m['tp']} fp={m['fp']} tn={m['tn']} fn={m['fn']}  "
          f"breach κ={report['breach_kappa']:.2f}  severity κ={report['severity_kappa']:.2f}")
    for f in report["flags"]:
        print(_color(f"  ⚠ {f}", "yellow"))
    print(f"  report: {out}")
    if getattr(args, "min_f1", None) is not None and m["f1"] < args.min_f1:
        print(_color(f"calibration gate: F1 {m['f1']:.2f} < {args.min_f1:.2f}", "red"))
        return 1
    return 0


def cmd_manifest(cfg: Config, args) -> int:
    from . import provenance as P

    store = _store(cfg)
    meta = store.get_run(args.run)
    if meta is None:
        print(_color(f"no such run: {args.run}", "red"))
        return 1
    manifest = P.eval_provenance(meta, cfg)
    out = _run_dir(cfg, args.run) / "provenance.json"
    _save_json(out, manifest)
    print(f"  provenance: {out}")
    tp = manifest["tool"]
    print(_color(f"  {tp['tool']} {tp['version']} · python {tp['python']} · "
                 f"{len(tp['dependencies'])} deps pinned", "dim"))
    return 0


def cmd_references(cfg: Config, args) -> int:
    from . import provenance as P

    if args.write:
        p = P.write_reference_lock()
        print(_color(f"wrote reference lock: {p}", "green"))
        return 0
    res = P.check_reference_integrity()
    if res["ok"]:
        print(_color(f"reference integrity OK — {res['reason']} ({res['actual'][:12]})", "green"))
        return 0
    print(_color(f"reference integrity FAILED — {res['reason']}", "red"))
    if res.get("expected"):
        print(f"  expected {res['expected'][:12]}, got {res['actual'][:12]}")
    return 1


def cmd_scaffold_ci(cfg: Config, args) -> int:
    from .scaffold import scaffold_ci

    res = scaffold_ci(args.provider, config=args.config_path, force=args.force)
    if res["skipped"]:
        print(_color(f"{res['path']} exists — pass --force to overwrite", "yellow"))
        return 0
    print(_color(f"wrote {res['path']}", "green"))
    print(_color(f"edit the config path ({args.config_path}) and drop --mock once an adapter "
                 "points at your system", "dim"))
    return 0


def cmd_schema(cfg: Config, args) -> int:
    from .schema_gen import write_schemas

    written = write_schemas(args.out)
    for name, path in written.items():
        print(f"  {name}: {path}")
    print(_color(f"add  # yaml-language-server: $schema={written['config']}  "
                 "to a config for editor validation", "dim"))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # These commands must not eagerly load/validate the config (that is their job),
    # so they run on a bare default Config before the loader can raise.
    if args.cmd == "validate-config":
        return cmd_validate_config(Config(), args)
    if args.cmd == "schema":
        return cmd_schema(Config(), args)
    if args.cmd == "scaffold-ci":
        return cmd_scaffold_ci(Config(), args)
    if args.cmd == "references":
        return cmd_references(Config(), args)
    cfg = _load_cfg(args)
    if args.cmd == "init":
        return cmd_init(cfg, args)
    elif args.cmd == "run":
        cmd_run(cfg, args)
    elif args.cmd == "generate":
        cmd_generate(cfg, args)
    elif args.cmd == "analyze":
        summary = cmd_analyze(cfg, args.run)
        if getattr(args, "ci", False) or getattr(args, "github_annotations", False) \
                or getattr(args, "pr_comment", None) or getattr(args, "baseline", None):
            _ci_feedback(cfg, args, summary)
        return A.ci_exit_code(summary) if getattr(args, "ci", False) else 0
    elif args.cmd == "audit":
        cmd_audit(cfg, args.run)
    elif args.cmd == "report":
        cmd_report(cfg, args.run, args.format.split(","), baseline_id=args.baseline)
    elif args.cmd == "compare":
        cmd_compare(cfg, args)
    elif args.cmd == "trend":
        cmd_trend(cfg, args)
    elif args.cmd == "regressions":
        cmd_regressions(cfg, args)
    elif args.cmd == "personas":
        cmd_personas(cfg, args)
    elif args.cmd == "dashboard":
        cmd_dashboard(cfg, args)
    elif args.cmd == "export":
        cmd_export(cfg, args)
    elif args.cmd == "elicit":
        cmd_elicit(cfg, args)
    elif args.cmd == "tune":
        cmd_tune(cfg, args)
    elif args.cmd == "redteam":
        if getattr(args, "redteam_cmd", None) == "profiles":
            cmd_redteam_profiles(cfg, args)
            return 0
        return cmd_redteam(cfg, args)
    elif args.cmd == "all":
        return cmd_all(cfg, args)
    elif args.cmd == "manifest":
        return cmd_manifest(cfg, args)
    elif args.cmd == "calibrate":
        return cmd_calibrate(cfg, args)
    elif args.cmd == "validate-config":
        return cmd_validate_config(cfg, args)
    elif args.cmd == "schema":
        return cmd_schema(cfg, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
