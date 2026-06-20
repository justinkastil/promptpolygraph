"""Store-driven pipeline orchestration: run -> analyze -> audit -> report.

This is the single place that wires the engine modules together against a
`Store`, so both a worker (service mode) and a one-shot caller share identical
behavior. The CLI keeps its own thin orchestration for the local file layout;
this function is for callers that hold a store and a run id (the service).

`progress_cb(stage, info)` is invoked at each stage boundary so a worker can
surface live status; it may be None.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Optional

from . import analyze as A
from . import audit as AU
from . import corpus as C
from . import persona as P
from .adapters import build_adapter
from .config import Config
from .models import RunMeta, config_fingerprint, fingerprint, rubric_fingerprint
from .runner.runner import Runner, RunnerOptions

ProgressCb = Optional[Callable[[str, dict], None]]


def _mock(cfg: Config) -> bool:
    if cfg.mock:
        return True
    from .llm import provider_needs_key

    env = provider_needs_key(cfg.llm.provider, cfg.llm.api_key_env)
    return bool(env) and not os.environ.get(env)


def _client(cfg: Config):
    from .llm import make_client

    if _mock(cfg):
        return None
    return make_client(
        cfg.model or cfg.analyze.judge_model,
        provider=cfg.llm.provider, base_url=cfg.llm.base_url, api_key_env=cfg.llm.api_key_env,
    )


def _build_sample(cases, responses, scores, per_category: int) -> list[dict]:
    rmap = {r.case_id: r for r in responses}
    smap = {s.case_id: s for s in scores}
    by_cat: dict[str, list] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)

    def mean(s) -> float:
        vals = [v for v in (s.dimensions.values() if s else []) if v is not None]
        return sum(vals) / len(vals) if vals else 0.0

    out: list[dict] = []
    for cat, cs in by_cat.items():
        graded = [c for c in cs if rmap.get(c.id) and (rmap[c.id].text or "").strip()]
        graded.sort(key=lambda c: mean(smap.get(c.id)))
        pick = graded[: max(1, per_category - 1)] + (graded[-1:] if len(graded) > 1 else [])
        seen = set()
        for c in pick:
            if c.id in seen:
                continue
            seen.add(c.id)
            s = smap.get(c.id)
            out.append({
                "category": cat, "case_id": c.id, "prompt": c.prompt,
                "response": rmap[c.id].text if c.id in rmap else "",
                "rubric_scores": {k: v for k, v in (s.dimensions if s else {}).items() if v is not None},
                "expected_behavior": c.expected_behavior,
            })
    return out


async def run_pipeline(
    cfg: Config,
    store,
    *,
    run_id: str,
    out_dir: str | None = None,
    progress: ProgressCb = None,
    do_audit: bool | None = None,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    """Execute the full pipeline for `run_id` against `store`. Returns a result dict."""

    def emit(stage: str, info: dict | None = None) -> None:
        if progress:
            progress(stage, info or {})

    mock = _mock(cfg)
    client = _client(cfg)
    rd = Path(out_dir or cfg.out_dir).expanduser() / run_id
    rd.mkdir(parents=True, exist_ok=True)

    # 1. corpus
    emit("corpus", {"mode": cfg.corpus.mode, "domain": cfg.domain})
    cases = C.build_corpus(cfg.corpus, resolve=cfg.resolve, client=client, mock=mock, domain=cfg.domain)

    adapter = build_adapter(cfg.adapter)
    meta = RunMeta(
        run_id=run_id, name=cfg.name, mode=cfg.corpus.mode, adapter=adapter.name,
        model=cfg.model, total_cases=len(cases), corpus_fingerprint=fingerprint(cases),
        config=cfg.model_dump(mode="json"),
        project=os.environ.get("POLYGRAPH_PROJECT") or cfg.name or "default",
        config_fingerprint=config_fingerprint(cfg.model_dump(mode="json")),
        sut_git_sha=os.environ.get("POLYGRAPH_SUT_GIT_SHA"),
        sut_ref=os.environ.get("POLYGRAPH_SUT_REF"),
    )
    store.save_run(meta)
    store.save_cases(run_id, cases)

    # 2. run
    emit("run", {"total": len(cases)})
    opts = RunnerOptions(
        concurrency=cfg.run.concurrency, rps=cfg.run.rps, timeout_s=cfg.run.timeout_s,
        retries=cfg.run.retries, resume=cfg.run.resume,
    )
    done = {"n": 0}

    def _on(_resp):
        done["n"] += 1
        if done["n"] % 10 == 0 or done["n"] == len(cases):
            emit("run", {"completed": done["n"], "total": len(cases)})

    runner = Runner(adapter, store, run_id, opts, adapter_sig=cfg.adapter.options, on_done=_on)
    try:
        responses = await runner.run(cases)
    finally:
        await adapter.aclose()
    meta.completed_cases = sum(1 for r in responses if not r.error)
    store.save_run(meta)

    # 3. analyze
    emit("analyze", {"judges": cfg.analyze.judges})
    rubric = A.load_rubric(cfg.resolve(cfg.analyze.rubric)) if cfg.analyze.rubric else A.default_rubric()
    meta.rubric_fingerprint = rubric_fingerprint(rubric)
    meta.judge_meta = A.judge_identity(rubric, cfg, mock=mock)
    store.save_run(meta)
    scores = await A.analyze_run(
        cases, responses, rubric, client=client, judges=cfg.analyze.judges,
        model=cfg.analyze.judge_model or cfg.model, temperature=cfg.analyze.temperature, mock=mock,
        config=cfg,
    )
    for s in scores:
        store.save_score(run_id, s)
    summary = A.summarize(cases, responses, scores, rubric, config=cfg)
    _write_json(rd / "summary.json", summary)
    store.export_jsonl(run_id, rd / "cases.jsonl")

    # 4. audit
    audit = None
    want_audit = cfg.audit.enabled if do_audit is None else do_audit
    if want_audit:
        emit("audit", {})
        personas = _resolve_personas(cfg, client=client, mock=mock)
        sample = _build_sample(cases, responses, scores, cfg.audit.sample_per_category)
        audit = await AU.run_audit(
            cases, responses, scores, rubric, personas, sample,
            client=client, code_path=cfg.resolve(cfg.audit.code_path),
            forensic=cfg.audit.forensic, mock=mock,
        )
        _write_json(rd / "audit.json", audit)

    # 5. report
    fmts = formats or ["md", "html"]
    emit("report", {"formats": fmts})
    from .report import build_report

    paths = build_report(
        meta, cases, responses, scores, summary,
        rubric=rubric, audit=audit, formats=fmts, out_dir=str(rd),
        template=cfg.report.template, template_dir=cfg.resolve(cfg.report.template_dir),
        branding=cfg.report.branding,
    )

    meta.completed_at = RunMeta().created_at
    store.save_run(meta)
    emit("done", {"verdict": summary.get("overall_pass")})
    return {
        "run_id": run_id, "summary": summary, "reports": paths,
        "completed_cases": meta.completed_cases, "total_cases": len(cases),
        "overall_pass": summary.get("overall_pass"),
    }


def _resolve_personas(cfg: Config, *, client=None, mock: bool = False) -> list:
    if cfg.personas_path:
        return P.load_personas_file(cfg.resolve(cfg.personas_path))
    if cfg.audit.personas:
        return P.select(cfg.audit.personas)
    # When a domain is set and tailoring is requested, synthesize a panel
    # specific to that domain instead of sampling the generic library.
    if cfg.audit.tailor_personas and cfg.domain:
        import asyncio

        n = cfg.audit.persona_pool or 6
        return asyncio.run(P.generate_panel(client, n, cfg.domain, mock=mock))
    return P.sample_pool(cfg.audit.persona_pool or 5, seed=cfg.corpus.seed)


def _write_json(path: Path, obj: Any) -> None:
    import json

    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
