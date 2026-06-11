"""PromptPolygraph command-line interface.

Subcommands:
  run       corpus -> adapter -> store (the target queries)
  generate  synthesize a corpus (varied | adversarial) to files
  analyze   score a run's responses against the rubric
  audit     persona panel + forensic audit over a run
  report    render markdown / docx / pdf / html
  compare   A/B two runs (pairwise win/loss/tie)
  personas  list the library / create one / generate a panel
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
from .compare import pairwise as pairwise_fn
from .config import Config
from .llm import make_client
from .models import Case, Response, RunMeta, Score, fingerprint
from .report import build_report
from .runner import SQLiteStore
from .runner.runner import Runner, RunnerOptions, run_corpus


# ─── helpers ──────────────────────────────────────────────────────────────


def _is_mock(cfg: Config) -> bool:
    if cfg.mock:
        return True
    return not os.environ.get("ANTHROPIC_API_KEY")


def _client(cfg: Config):
    if _is_mock(cfg):
        return None
    return make_client(cfg.model or cfg.analyze.judge_model)


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
    client = _client(cfg)
    cases = C.build_corpus(cfg.corpus, resolve=cfg.resolve, client=client, mock=_is_mock(cfg), domain=cfg.domain)
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
            temperature=cfg.analyze.temperature, mock=_is_mock(cfg),
        )
    )
    for s in scores:
        store.save_score(run_id, s)
    summary = A.summarize(cases, responses, scores, rubric)
    _save_json(_run_dir(cfg, run_id) / "summary.json", summary)
    store.export_jsonl(run_id, _run_dir(cfg, run_id) / "cases.jsonl")
    _print_summary(summary)
    return summary


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
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else A.summarize(cases, responses, scores, rubric)
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


def cmd_compare(cfg: Config, run_a: str, run_b: str) -> dict:
    store = _store(cfg)
    cases = store.get_cases(run_a)
    pw = pairwise_fn(cases, store.get_scores(run_a), store.get_scores(run_b))
    pw["run_a"], pw["run_b"] = run_a, run_b
    _save_json(_run_dir(cfg, run_a) / f"pairwise_vs_{run_b}.json", pw)
    print(f"A/B {run_a[:8]} vs {run_b[:8]}: "
          f"wins_a={pw.get('wins_a')} wins_b={pw.get('wins_b')} ties={pw.get('ties')}")
    return pw


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
    p.add_argument("--mode", choices=["fixed", "varied", "adversarial", "hybrid"])
    p.add_argument("--count", type=int)
    p.add_argument("--per-category", dest="per_category", type=int)
    p.add_argument("--categories")
    p.add_argument("--difficulty", choices=["mild", "standard", "aggressive"])
    p.add_argument("--concurrency", type=int)
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

    pu = sub.add_parser("audit", parents=[common], help="persona + forensic audit of a run")
    pu.add_argument("--run", required=True)

    prp = sub.add_parser("report", parents=[common], help="render a report")
    prp.add_argument("--run", required=True)
    prp.add_argument("--format", default="md,html")
    prp.add_argument("--baseline", help="prior run id for delta columns")

    pc = sub.add_parser("compare", parents=[common], help="A/B two runs")
    pc.add_argument("--run-a", dest="run_a", required=True)
    pc.add_argument("--run-b", dest="run_b", required=True)

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

    pall = sub.add_parser("all", parents=[common], help="run -> analyze -> audit -> report")
    _add_corpus_dials(pall)
    pall.add_argument("--callable", help="module:function in-process adapter")
    pall.add_argument("--judges", type=int)
    pall.add_argument("--format", default="md,html")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = _load_cfg(args)
    if args.cmd == "run":
        cmd_run(cfg, args)
    elif args.cmd == "generate":
        cmd_generate(cfg, args)
    elif args.cmd == "analyze":
        summary = cmd_analyze(cfg, args.run)
        return A.ci_exit_code(summary) if getattr(args, "ci", False) else 0
    elif args.cmd == "audit":
        cmd_audit(cfg, args.run)
    elif args.cmd == "report":
        cmd_report(cfg, args.run, args.format.split(","), baseline_id=args.baseline)
    elif args.cmd == "compare":
        cmd_compare(cfg, args.run_a, args.run_b)
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
    elif args.cmd == "all":
        return cmd_all(cfg, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
