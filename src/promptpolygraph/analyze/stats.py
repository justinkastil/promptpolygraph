"""Confidence intervals, significance tests, and reliability for run metrics.

Proportions (ASR, pass rate, breach rate) get a Wilson-score interval; continuous
aggregates (mean dimension score, agreement) get a percentile bootstrap interval;
run-over-run changes get a significance test with multiple-comparison correction.

Pure-Python and deterministic (the bootstrap is seeded), so it runs offline with
no scientific stack and reproduces byte-for-byte. The numerical helpers
(inverse-normal, Student-t two-sided p via the regularized incomplete beta) are
unit-tested against reference values.

Interval helpers return a metric-with-uncertainty dict::

    {"value": 0.12, "ci_lower": 0.055, "ci_upper": 0.235, "n": 50,
     "method": "wilson", "confidence": 0.95}
"""

from __future__ import annotations

import math
import random
from statistics import mean as _mean
from typing import Callable, Sequence

__all__ = [
    "norm_ppf",
    "norm_cdf",
    "z_for_confidence",
    "wilson_interval",
    "proportion_ci",
    "bootstrap_ci",
    "mean_ci",
    "two_proportion_ztest",
    "welch_ttest",
    "mcnemar_test",
    "benjamini_hochberg",
    "gate_band_decision",
    "binary_classification_metrics",
    "cohen_kappa",
    "fleiss_kappa",
    "sample_size_for_proportion",
    "min_n_for_proportion_diff",
    "power_for_proportion_diff",
    "variance_components",
]


# ── numerical primitives ─────────────────────────────────────────────────────

def norm_cdf(x: float) -> float:
    """Standard-normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile) — Acklam's rational approximation.

    Accurate to ~1e-9 over the open interval; clamps the boundaries.
    """
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    # coefficients
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def z_for_confidence(confidence: float = 0.95) -> float:
    """Two-sided z multiplier for a confidence level (0.95 -> ~1.959964)."""
    confidence = min(max(confidence, 1e-6), 1 - 1e-9)
    return norm_ppf(1 - (1 - confidence) / 2.0)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    MAXIT, EPS, FPMIN = 200, 3.0e-12, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value for a Student-t statistic with df degrees of freedom."""
    if df <= 0:
        return 1.0
    t = abs(t)
    if t == 0.0:
        return 1.0
    return _betai(df / 2.0, 0.5, df / (df + t * t))


# ── proportion intervals ─────────────────────────────────────────────────────

def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal (Wald) interval: it never leaves [0, 1] and stays
    sensible at the extremes and for small n — exactly the regimes red-team ASR
    and refusal rates live in.
    """
    if n <= 0:
        return (0.0, 0.0)
    z = z_for_confidence(confidence)
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion_ci(successes: int, n: int, confidence: float = 0.95) -> dict:
    """A proportion with its Wilson confidence interval, as the standard dict."""
    lo, hi = wilson_interval(successes, n, confidence)
    return {
        "value": round(successes / n, 6) if n else 0.0,
        "ci_lower": round(lo, 6),
        "ci_upper": round(hi, 6),
        "n": int(n),
        "method": "wilson",
        "confidence": confidence,
    }


# ── continuous intervals ─────────────────────────────────────────────────────

def bootstrap_ci(
    values: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float] = _mean,
    confidence: float = 0.95,
    n_resamples: int = 2000,
    seed: int = 1234,
) -> dict:
    """Nonparametric percentile-bootstrap CI for a sample statistic.

    Deterministic for a fixed seed so runs reproduce byte-for-byte. Falls back
    to the point value with a zero-width band for n < 2.
    """
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"value": None, "ci_lower": None, "ci_upper": None, "n": 0, "method": "bootstrap"}
    point = float(statistic(vals))
    if n < 2:
        return {"value": round(point, 6), "ci_lower": round(point, 6),
                "ci_upper": round(point, 6), "n": n, "method": "bootstrap"}
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(n_resamples):
        sample = [vals[rng.randrange(n)] for _ in range(n)]
        stats.append(float(statistic(sample)))
    stats.sort()
    alpha = (1 - confidence) / 2.0
    lo = stats[max(0, int(math.floor(alpha * n_resamples)))]
    hi = stats[min(n_resamples - 1, int(math.ceil((1 - alpha) * n_resamples)) - 1)]
    return {
        "value": round(point, 6),
        "ci_lower": round(lo, 6),
        "ci_upper": round(hi, 6),
        "n": n,
        "method": "bootstrap",
        "confidence": confidence,
    }


def mean_ci(values: Sequence[float], *, confidence: float = 0.95) -> dict:
    """Student-t confidence interval for a sample mean (parametric)."""
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"value": None, "ci_lower": None, "ci_upper": None, "n": 0, "method": "t"}
    m = _mean(vals)
    if n < 2:
        return {"value": round(m, 6), "ci_lower": round(m, 6), "ci_upper": round(m, 6),
                "n": n, "method": "t"}
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    se = math.sqrt(var / n)
    # invert the t two-sided p to get the critical t for this confidence.
    tcrit = _t_crit(confidence, n - 1)
    half = tcrit * se
    return {"value": round(m, 6), "ci_lower": round(m - half, 6),
            "ci_upper": round(m + half, 6), "n": n, "method": "t", "confidence": confidence}


def _t_crit(confidence: float, df: int) -> float:
    """Critical two-sided t value via bisection on the t two-sided p-value."""
    target = 1 - confidence
    lo, hi = 0.0, 1000.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _t_two_sided_p(mid, df) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ── significance tests ───────────────────────────────────────────────────────

def two_proportion_ztest(s1: int, n1: int, s2: int, n2: int) -> dict:
    """Two-proportion z-test (pooled). delta = p2 - p1 (b vs a).

    Use for ASR / pass-rate change between two independent runs.
    """
    if n1 <= 0 or n2 <= 0:
        return {"delta": 0.0, "z": 0.0, "p_value": 1.0, "n1": n1, "n2": n2}
    p1, p2 = s1 / n1, s2 / n2
    pool = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        z = 0.0
        p = 1.0
    else:
        z = (p2 - p1) / se
        p = 2 * (1 - norm_cdf(abs(z)))
    return {"delta": round(p2 - p1, 6), "z": round(z, 6), "p_value": round(p, 6),
            "p1": round(p1, 6), "p2": round(p2, 6), "n1": n1, "n2": n2}


def welch_ttest(a: Sequence[float], b: Sequence[float]) -> dict:
    """Welch's unequal-variance t-test. delta = mean(b) - mean(a)."""
    a = [float(x) for x in a if x is not None]
    b = [float(x) for x in b if x is not None]
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return {"delta": (_mean(b) - _mean(a)) if (a and b) else 0.0,
                "t": 0.0, "df": 0.0, "p_value": 1.0, "se": 0.0, "na": na, "nb": nb}
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return {"delta": round(mb - ma, 6), "t": 0.0, "df": 0.0, "p_value": 1.0,
                "se": 0.0, "na": na, "nb": nb}
    t = (mb - ma) / se
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    )
    p = _t_two_sided_p(t, df)
    return {"delta": round(mb - ma, 6), "t": round(t, 6), "df": round(df, 4),
            "p_value": round(p, 6), "se": round(se, 6), "na": na, "nb": nb}


def mcnemar_test(b: int, c: int) -> dict:
    """McNemar's test for paired binary outcomes (same items, two conditions).

    `b` = items that passed before and fail now; `c` = failed before, pass now.
    Uses the exact binomial p-value (robust for the small discordant counts a
    per-case pass/fail diff produces).
    """
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "p_value": 1.0, "statistic": 0.0}
    # exact two-sided binomial test at p=0.5 over the discordant pairs.
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    p = min(1.0, 2 * tail)
    stat = (abs(b - c) - 1) ** 2 / n if n > 0 else 0.0  # continuity-corrected chi-sq
    return {"b": b, "c": c, "p_value": round(p, 6), "statistic": round(stat, 6)}


def benjamini_hochberg(pvalues: Sequence[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg FDR control across many simultaneous tests.

    Returns rejection flags (in the input order) and BH-adjusted q-values. This
    is what stops a multi-dimension regression sweep from crying wolf: testing
    many dimensions inflates false positives, BH corrects for it.
    """
    m = len(pvalues)
    if m == 0:
        return {"rejected": [], "qvalues": [], "alpha": alpha, "n_significant": 0}
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    prev = 1.0
    # step-up: walk from largest p to smallest, enforcing monotone q-values.
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        val = min(prev, pvalues[idx] * m / rank)
        q[idx] = val
        prev = val
    rejected = [q[i] <= alpha for i in range(m)]
    return {"rejected": rejected, "qvalues": [round(x, 6) for x in q],
            "alpha": alpha, "n_significant": sum(rejected)}


# ── classification + agreement (judge calibration) ───────────────────────────

def binary_classification_metrics(y_true: Sequence[bool], y_pred: Sequence[bool]) -> dict:
    """Precision/recall/F1/accuracy + confusion counts for a binary classifier.

    `y_true` is ground truth, `y_pred` the judge's call. The positive class is
    True (e.g. "breached"). Returns zeros (not errors) on the degenerate cases.
    """
    tp = fp = tn = fn = 0
    for t, p in zip(y_true, y_pred):
        if p and t:
            tp += 1
        elif p and not t:
            fp += 1
        elif not p and t:
            fn += 1
        else:
            tn += 1
    n = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + tn) / n if n else 0.0
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn, "n": n,
        "precision": round(precision, 6), "recall": round(recall, 6),
        "f1": round(f1, 6), "accuracy": round(accuracy, 6),
    }


def cohen_kappa(a: Sequence[Any], b: Sequence[Any]) -> float:
    """Cohen's κ — agreement between two raters corrected for chance.

    Works for any categorical labels (bool, severity strings, …). 1.0 is perfect
    agreement, 0.0 is chance, negative is worse than chance.
    """
    pairs = list(zip(a, b))
    n = len(pairs)
    if n == 0:
        return 0.0
    cats = set(a) | set(b)
    po = sum(1 for x, y in pairs if x == y) / n
    ca = {c: sum(1 for x in a if x == c) / n for c in cats}
    cb = {c: sum(1 for y in b if y == c) / n for c in cats}
    pe = sum(ca[c] * cb[c] for c in cats)
    if pe >= 1.0:
        return 1.0  # everyone in one category and agreeing
    return round((po - pe) / (1 - pe), 6)


def fleiss_kappa(ratings: Sequence[Sequence[Any]], categories: Sequence[Any] | None = None) -> float:
    """Fleiss' κ — agreement among a fixed number of raters over N items.

    `ratings[i]` is the list of each rater's label for item i (same length per
    item). Used for an ensemble of ≥3 judges. Returns 0.0 if undefined.
    """
    items = [list(r) for r in ratings if r]
    if not items:
        return 0.0
    n_raters = len(items[0])
    if n_raters < 2 or any(len(r) != n_raters for r in items):
        return 0.0
    cats = list(categories) if categories is not None else sorted(
        {lbl for r in items for lbl in r}, key=str)
    N = len(items)
    # P_i: agreement within item i
    Pi = []
    cat_totals = {c: 0 for c in cats}
    for r in items:
        counts = {c: r.count(c) for c in cats}
        for c in cats:
            cat_totals[c] += counts[c]
        Pi.append((sum(v * v for v in counts.values()) - n_raters) / (n_raters * (n_raters - 1)))
    Pbar = sum(Pi) / N
    pj = {c: cat_totals[c] / (N * n_raters) for c in cats}
    Pe = sum(v * v for v in pj.values())
    if Pe >= 1.0:
        return 1.0
    return round((Pbar - Pe) / (1 - Pe), 6)


# ── gate helpers ─────────────────────────────────────────────────────────────

def gate_band_decision(
    ci_lower: float | None,
    ci_upper: float | None,
    threshold: float,
    *,
    direction: str = "above",
) -> str:
    """Gate verdict that respects the confidence band.

    `direction="above"` means the metric should be >= threshold (e.g. a quality
    dimension); `"below"` means it should be <= threshold (e.g. ASR). The
    verdict is:

    - ``pass``         — the whole interval is on the good side of the threshold.
    - ``fail``         — the whole interval is on the bad side.
    - ``inconclusive`` — the threshold falls inside the interval: the run has not
      gathered enough evidence to call it either way. CI should warn, not fail,
      so noise does not flip a build red.
    """
    if ci_lower is None or ci_upper is None:
        return "inconclusive"
    if direction == "below":
        if ci_upper <= threshold:
            return "pass"
        if ci_lower > threshold:
            return "fail"
        return "inconclusive"
    # default: above
    if ci_lower >= threshold:
        return "pass"
    if ci_upper < threshold:
        return "fail"
    return "inconclusive"


# ── sample-size / power planning ──────────────────────────────────────────────

def sample_size_for_proportion(margin: float, *, confidence: float = 0.95,
                               p: float = 0.5) -> int:
    """How many probes to estimate a proportion (e.g. ASR) to ±`margin`.

    Uses the worst-case p=0.5 by default; pass a planning `p` if you expect a
    rate far from 0.5. Returns a rounded-up sample size.
    """
    if margin <= 0:
        raise ValueError("margin must be > 0")
    z = z_for_confidence(confidence)
    return int(math.ceil(z * z * p * (1 - p) / (margin * margin)))


def min_n_for_proportion_diff(p1: float, p2: float, *, power: float = 0.8,
                              alpha: float = 0.05) -> int:
    """Per-group sample size to detect a rate change p1→p2 (the MDE) at a target
    power. Two-sided. Returns probes *per run* (current and baseline)."""
    if p1 == p2:
        return 0
    za = norm_ppf(1 - alpha / 2)
    zb = norm_ppf(power)
    pbar = (p1 + p2) / 2
    num = za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return int(math.ceil((num / (p2 - p1)) ** 2))


def power_for_proportion_diff(p1: float, p2: float, n1: int, n2: int,
                              *, alpha: float = 0.05) -> float:
    """Achieved power to detect p1 vs p2 at the given per-group sizes (two-sided)."""
    if n1 <= 0 or n2 <= 0 or p1 == p2:
        return 0.0
    za = norm_ppf(1 - alpha / 2)
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    if se == 0:
        return 1.0
    z = abs(p2 - p1) / se
    return round(max(0.0, min(1.0, norm_cdf(z - za) + norm_cdf(-z - za))), 6)


# ── variance decomposition (judge noise vs real signal) ───────────────────────

def variance_components(per_item_ratings: Sequence[Sequence[float]]) -> dict:
    """One-way random-effects decomposition of score variance.

    `per_item_ratings[i]` is the list of each judge's score for item i (a fixed
    number of judges per item). Splits total variance into a between-item
    component (real differences between cases) and a within-item component (judge
    disagreement = measurement noise), and reports **ICC(1)** — the fraction of
    variance that is real signal. A low ICC means the ensemble is noisy and the
    per-case numbers should be read with caution.
    """
    items = [[float(x) for x in row if x is not None] for row in per_item_ratings]
    items = [row for row in items if row]
    n = len(items)
    if n < 2:
        return {"icc": None, "between_var": None, "within_var": None,
                "n_items": n, "n_raters": (len(items[0]) if items else 0),
                "reason": "need >= 2 items"}
    k = len(items[0])
    if k < 2 or any(len(row) != k for row in items):
        return {"icc": None, "between_var": None, "within_var": None,
                "n_items": n, "n_raters": k, "reason": "need a fixed >= 2 raters per item"}
    grand = _mean([v for row in items for v in row])
    item_means = [_mean(row) for row in items]
    # one-way ANOVA mean squares
    ss_between = k * sum((m - grand) ** 2 for m in item_means)
    ss_within = sum((v - im) ** 2 for row, im in zip(items, item_means) for v in row)
    ms_between = ss_between / (n - 1)
    ms_within = ss_within / (n * (k - 1)) if (n * (k - 1)) else 0.0
    denom = ms_between + (k - 1) * ms_within
    icc = (ms_between - ms_within) / denom if denom > 0 else 0.0
    icc = max(-1.0, min(1.0, icc))
    return {
        "icc": round(icc, 6),
        "between_var": round(ms_between, 6),
        "within_var": round(ms_within, 6),
        "n_items": n, "n_raters": k,
        "interpretation": ("excellent" if icc >= 0.9 else "good" if icc >= 0.75
                           else "moderate" if icc >= 0.5 else "poor"),
    }
