"""Deterministic, code-checkable assertions over a response.

These run before any LLM judge and are cheap. Every spec is evaluated
defensively: a malformed spec produces a failed `AssertionResult` rather than
raising, so one bad probe can never abort a batch.

v0.3 adds weighted/threshold/negate/metric-tagged results, a continuous `value`
in [0, 1] per result, several new kinds (icontains, contains_any, contains_all,
starts_with, is_refusal, levenshtein, cost_under, similar), and a sandboxed
custom-code kind (python/callable). `score_assertions` returns the weighted
aggregate `assertion_score`. The original `evaluate_assertions` (results,
all_passed) signature is preserved for backward compatibility.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import operator
import re
from typing import Any

from ..models import AssertionResult, AssertionSpec, Case, Response

# ─── AST-restricted expression sandbox (shared with gate.py derived metrics) ──


class SandboxError(Exception):
    """Raised for any disallowed or malformed sandbox expression."""


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _forbid_dunder(name: str) -> None:
    if name.startswith("__") and name.endswith("__"):
        raise SandboxError(f"dunder access is not allowed: {name!r}")


def _sb_eval(node: ast.AST, names: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _sb_eval(node.body, names)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        _forbid_dunder(node.id)
        if node.id not in names:
            raise SandboxError(f"unknown name: {node.id!r}")
        return names[node.id]
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise SandboxError(f"operator not allowed: {type(node.op).__name__}")
        return op(_sb_eval(node.left, names), _sb_eval(node.right, names))
    if isinstance(node, ast.UnaryOp):
        op = _UNARYOPS.get(type(node.op))
        if op is None:
            raise SandboxError(f"unary op not allowed: {type(node.op).__name__}")
        return op(_sb_eval(node.operand, names))
    if isinstance(node, ast.BoolOp):
        out: Any = isinstance(node.op, ast.And)
        for v in node.values:
            out = _sb_eval(v, names)
            if isinstance(node.op, ast.And) and not out:
                break
            if isinstance(node.op, ast.Or) and out:
                break
        return out
    if isinstance(node, ast.Compare):
        left = _sb_eval(node.left, names)
        for op_node, comp in zip(node.ops, node.comparators):
            op = _CMPOPS.get(type(op_node))
            if op is None:
                raise SandboxError(f"comparison not allowed: {type(op_node).__name__}")
            right = _sb_eval(comp, names)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return (
            _sb_eval(node.body, names)
            if _sb_eval(node.test, names)
            else _sb_eval(node.orelse, names)
        )
    if isinstance(node, ast.Subscript):
        return _sb_eval(node.value, names)[_sb_eval(node.slice, names)]
    if isinstance(node, ast.Attribute):
        _forbid_dunder(node.attr)
        return getattr(_sb_eval(node.value, names), node.attr)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            _forbid_dunder(node.func.id)
            if node.func.id not in names:
                raise SandboxError(f"call to unknown function: {node.func.id!r}")
            fn = names[node.func.id]
        elif isinstance(node.func, ast.Attribute):
            fn = _sb_eval(node.func, names)
        else:
            raise SandboxError("only simple/attribute calls are allowed")
        args = [_sb_eval(a, names) for a in node.args]
        kwargs = {kw.arg: _sb_eval(kw.value, names) for kw in node.keywords if kw.arg}
        return fn(*args, **kwargs)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_sb_eval(e, names) for e in node.elts]
    raise SandboxError(f"expression node not allowed: {type(node).__name__}")


def safe_eval(expr: str, names: dict[str, Any]) -> Any:
    """Evaluate a single expression over `names` with no builtins. Raises
    SandboxError on imports, dunders, or any node outside the allow-list."""
    if not isinstance(expr, str) or not expr.strip():
        raise SandboxError("empty expression")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise SandboxError(f"syntax error: {exc}") from exc
    for sub in ast.walk(tree):
        if isinstance(sub, (ast.Import, ast.ImportFrom)):
            raise SandboxError("imports are not allowed")
    return _sb_eval(tree, names)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _re_flags(flags: str) -> int:
    out = 0
    if "i" in flags:
        out |= re.IGNORECASE
    if "m" in flags:
        out |= re.MULTILINE
    if "s" in flags:
        out |= re.DOTALL
    return out


# Common refusal phrasings, kept domain-neutral.
_REFUSAL_MARKERS = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "i can't do that",
    "i cannot do that",
    "i'm not able to",
    "i am not able to",
    "i won't",
    "i will not",
    "i'm unable to",
    "i am unable to",
    "i can't provide",
    "i cannot provide",
    "i'm sorry, but i can't",
    "unable to assist",
    "not something i can help",
)


def _levenshtein_ratio(a: str, b: str) -> float:
    """Normalized similarity in [0, 1]: 1 - edit_distance / max(len)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    dist = prev[lb]
    return 1.0 - dist / max(la, lb)


def _result(
    spec: AssertionSpec, passed: bool, value: float, detail: str = ""
) -> AssertionResult:
    """Build a result, applying spec.negate and spec.threshold uniformly."""
    val = max(0.0, min(1.0, float(value)))
    p = bool(passed)
    if spec.negate:
        p = not p
        val = 1.0 - val
    if spec.threshold is not None:
        # Threshold overrides the boolean: pass iff continuous value >= threshold.
        p = val >= spec.threshold
        if not detail and not p:
            detail = f"value {val:.3f} < threshold {spec.threshold}"
    return AssertionResult(
        kind=spec.kind,
        passed=p,
        description=spec.description,
        detail="" if p else detail,
        value=val,
        weight=spec.weight,
        metric=spec.metric,
    )


# ─── Custom-code (python/callable) scorer ───────────────────────────────────


def _eval_custom(
    spec: AssertionSpec, case: Case, resp: Response, sandbox: str
) -> AssertionResult:
    text = resp.text or ""
    if sandbox == "disabled":
        return _result(
            spec, False, 0.0, "custom-code assertions disabled (scorers.sandbox)"
        )

    if spec.kind == "callable":
        ref = spec.options.get("ref")
        if not ref or ":" not in str(ref):
            return _result(spec, False, 0.0, "callable needs options.ref='mod:fn'")
        mod_name, _, fn_name = str(ref).partition(":")
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, fn_name)
            out = fn(resp, case)
        except Exception as exc:  # noqa: BLE001
            return _result(spec, False, 0.0, f"callable error: {exc}")
        if isinstance(out, bool):
            return _result(spec, out, 1.0 if out else 0.0)
        try:
            v = float(out)
        except (TypeError, ValueError):
            return _result(spec, False, 0.0, "callable returned non-bool/non-numeric")
        return _result(spec, v > 0.0, v)

    # kind == "python": evaluate options.expr in the AST sandbox.
    if sandbox not in ("expr", "subprocess"):
        return _result(spec, False, 0.0, f"unknown sandbox mode: {sandbox!r}")
    expr = spec.options.get("expr")
    if not expr:
        return _result(spec, False, 0.0, "python assertion needs options.expr")
    names = {"output": text, "case": case, "len": len, "re": re, "json": json}
    try:
        out = safe_eval(str(expr), names)
    except SandboxError as exc:
        return _result(spec, False, 0.0, f"sandbox rejected: {exc}")
    except Exception as exc:  # noqa: BLE001 - defensive
        return _result(spec, False, 0.0, f"expr error: {exc}")
    if isinstance(out, bool):
        return _result(spec, out, 1.0 if out else 0.0)
    try:
        v = float(out)
    except (TypeError, ValueError):
        return _result(spec, bool(out), 1.0 if out else 0.0)
    return _result(spec, v > 0.0, v)


# ─── Per-spec dispatch ──────────────────────────────────────────────────────


def _eval_one(
    spec: AssertionSpec,
    case: Case,
    resp: Response,
    *,
    similarity: float | None = None,
    sandbox: str = "disabled",
) -> AssertionResult:
    kind = spec.kind
    value = spec.value
    text = resp.text or ""

    try:
        if kind == "contains":
            needle = str(value)
            if "i" in spec.flags:
                passed = needle.lower() in text.lower()
            else:
                passed = needle in text
            return _result(spec, passed, 1.0 if passed else 0.0, f"missing substring: {needle!r}")

        if kind == "icontains":
            needle = str(value)
            passed = needle.lower() in text.lower()
            return _result(spec, passed, 1.0 if passed else 0.0, f"missing (ci) substring: {needle!r}")

        if kind == "not_contains":
            needle = str(value)
            if "i" in spec.flags:
                passed = needle.lower() not in text.lower()
            else:
                passed = needle not in text
            return _result(spec, passed, 1.0 if passed else 0.0, f"forbidden substring present: {needle!r}")

        if kind in ("contains_any", "contains_all"):
            needles = value if isinstance(value, (list, tuple)) else [value]
            needles = [str(n) for n in needles]
            ci = "i" in spec.flags
            hay = text.lower() if ci else text
            hits = [n for n in needles if (n.lower() if ci else n) in hay]
            if not needles:
                frac = 1.0
            else:
                frac = len(hits) / len(needles)
            if kind == "contains_any":
                passed = len(hits) > 0
                detail = f"none of {needles!r} present"
            else:
                passed = len(hits) == len(needles)
                missing = [n for n in needles if n not in hits]
                detail = f"missing: {missing!r}"
            return _result(spec, passed, frac, detail)

        if kind == "starts_with":
            prefix = str(value)
            t = text
            if "i" in spec.flags:
                passed = t.lower().lstrip().startswith(prefix.lower())
            else:
                passed = t.lstrip().startswith(prefix)
            return _result(spec, passed, 1.0 if passed else 0.0, f"does not start with {prefix!r}")

        if kind == "is_refusal":
            low = text.lower()
            passed = any(m in low for m in _REFUSAL_MARKERS)
            return _result(spec, passed, 1.0 if passed else 0.0, "no refusal phrasing detected")

        if kind == "levenshtein":
            target = str(value)
            ratio = _levenshtein_ratio(text, target)
            # boolean baseline: exact match; threshold (if set) gates on ratio.
            return _result(spec, text == target, ratio, f"levenshtein ratio {ratio:.3f}")

        if kind == "cost_under":
            n = float(value)
            cost = resp.cost_usd
            if cost is None:
                return _result(spec, False, 0.0, "no cost recorded")
            passed = cost <= n
            # value: 1.0 when free, decaying as cost approaches the cap.
            frac = 1.0 if n <= 0 else max(0.0, 1.0 - cost / n)
            return _result(spec, passed, frac, f"cost ${cost:.6f} > ${n}")

        if kind == "similar":
            if similarity is None:
                return _result(spec, False, 0.0, "no embedder available for 'similar'")
            # boolean baseline: a sensible default cutoff when no threshold set.
            passed = similarity >= 0.5
            return _result(spec, passed, similarity, f"similarity {similarity:.3f} below 0.5")

        if kind in ("python", "callable"):
            return _eval_custom(spec, case, resp, sandbox)

        if kind == "regex":
            passed = re.search(str(value), text, _re_flags(spec.flags)) is not None
            return _result(spec, passed, 1.0 if passed else 0.0, f"pattern did not match: {value!r}")

        if kind == "not_regex":
            passed = re.search(str(value), text, _re_flags(spec.flags)) is None
            return _result(spec, passed, 1.0 if passed else 0.0, f"forbidden pattern matched: {value!r}")

        if kind == "equals":
            passed = text == str(value)
            return _result(spec, passed, 1.0 if passed else 0.0, "text != expected value")

        if kind == "json_valid":
            json.loads(text)
            return _result(spec, True, 1.0)

        if kind == "json_schema":
            import jsonschema

            obj = json.loads(text)
            jsonschema.validate(instance=obj, schema=value)
            return _result(spec, True, 1.0)

        if kind == "min_length":
            n = int(value)
            passed = len(text) >= n
            return _result(spec, passed, 1.0 if passed else 0.0, f"len {len(text)} < {n}")

        if kind == "max_length":
            n = int(value)
            passed = len(text) <= n
            return _result(spec, passed, 1.0 if passed else 0.0, f"len {len(text)} > {n}")

        if kind == "max_latency_ms":
            n = float(value)
            lat = resp.latency_ms
            if lat is None:
                return _result(spec, False, 0.0, "no latency recorded")
            passed = lat <= n
            return _result(spec, passed, 1.0 if passed else 0.0, f"latency {lat}ms > {n}ms")

        if kind == "no_error":
            passed = resp.error is None
            return _result(spec, passed, 1.0 if passed else 0.0, f"error: {resp.error}")

        return _result(spec, False, 0.0, f"unknown assertion kind: {kind!r}")
    except Exception as exc:  # noqa: BLE001 - defensive: never raise to the batch
        return _result(spec, False, 0.0, f"assertion error: {exc}")


# ─── Public API ─────────────────────────────────────────────────────────────


async def _similarities(
    specs: list[AssertionSpec], resp: Response, embedder: Any
) -> dict[int, float]:
    """Compute cosine similarity for every `similar` spec (by index)."""
    from .embedders import cosine

    sim_idx = [i for i, s in enumerate(specs) if s.kind == "similar"]
    if not sim_idx or embedder is None:
        return {}
    texts = [resp.text or ""] + [str(specs[i].value) for i in sim_idx]
    try:
        vecs = await embedder.embed(texts)
    except Exception:  # noqa: BLE001 - never break on an embed call
        return {}
    base = vecs[0]
    out: dict[int, float] = {}
    for k, i in enumerate(sim_idx):
        out[i] = cosine(base, vecs[k + 1])
    return out


async def score_assertions(
    case: Case,
    resp: Response,
    *,
    embedder: Any = None,
    sandbox: str = "disabled",
    extra_specs: list[AssertionSpec] | None = None,
) -> tuple[list[AssertionResult], bool, float | None]:
    """Evaluate every assertion (case + optional shared `extra_specs`).

    Returns (results, all_passed, assertion_score) where
    `assertion_score = Σ(weightᵢ·valueᵢ) / Σ(weightᵢ)` over results whose value
    is not None. Never raises.
    """
    specs = list(case.assertions) + list(extra_specs or [])
    sims = await _similarities(specs, resp, embedder)
    results = [
        _eval_one(s, case, resp, similarity=sims.get(i), sandbox=sandbox)
        for i, s in enumerate(specs)
    ]
    all_passed = all(r.passed for r in results)
    num = 0.0
    den = 0.0
    for r in results:
        if r.value is None:
            continue
        num += r.weight * r.value
        den += r.weight
    score = (num / den) if den > 0 else None
    return results, all_passed, score


def evaluate_assertions(case: Case, resp: Response) -> tuple[list[AssertionResult], bool]:
    """Run every assertion spec on the case; return (results, all_passed).

    Backward-compatible synchronous entry point. Custom-code kinds default to the
    `disabled` sandbox and `similar` has no embedder here, matching prior safe
    behavior (those kinds did not exist before v0.3).
    """
    results = [_eval_one(spec, case, resp) for spec in case.assertions]
    all_passed = all(r.passed for r in results)
    return results, all_passed
