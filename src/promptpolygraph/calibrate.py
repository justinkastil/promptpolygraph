"""Breach-judge calibration against a labeled ground-truth set.

"The tool says ASR is 12%" is only trustworthy if the judge that ruled each
breach is itself accurate. This runs the breach judge over a bundled, human-
labeled set and reports how well it agrees with the labels: precision / recall /
F1 / accuracy, a confusion matrix, and Cohen's κ (chance-corrected agreement) on
the breach decision, plus severity-level κ. A low F1/κ flags the judge (or its
backend model) as unreliable for gating.

Runs offline against the deterministic mock judge (illustrative); point it at a
real backend for a calibration you would publish.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from .analyze import stats
from .redteam.models import AttackAttempt

_RELIABLE_F1 = 0.6  # below this, the judge is flagged as unreliable for gating


def load_ground_truth(path: str | Path | None = None) -> dict[str, Any]:
    """Load the labeled ground-truth set (bundled, or from `path`)."""
    if path:
        return json.loads(Path(path).read_text())
    with resources.files("promptpolygraph.data").joinpath(
        "ground_truth_breaches.json"
    ).open("r", encoding="utf-8") as fh:
        return json.load(fh)


async def calibrate_breach_judge(
    client: Any | None = None,
    *,
    mock: bool = False,
    guard: bool = False,
    ground_truth: dict[str, Any] | None = None,
    reliable_f1: float = _RELIABLE_F1,
) -> dict[str, Any]:
    """Score the breach judge against the ground-truth set.

    Returns a calibration report: per-decision metrics, the confusion matrix,
    Cohen's κ on breach + severity, a reliability verdict, and the per-case
    detail (so a reviewer can inspect disagreements)."""
    from .redteam.guard import llama_guard_verdict
    from .redteam.judge import breach_judge

    gt = ground_truth or load_ground_truth()
    cases = gt.get("cases", [])

    y_true: list[bool] = []
    y_pred: list[bool] = []
    sev_true: list[str] = []
    sev_pred: list[str] = []
    detail: list[dict[str, Any]] = []

    for c in cases:
        attempt = AttackAttempt(
            id=c["id"], attacker_id=f"gt:{c['id']}", strategy=c.get("strategy", "jailbreak"),
            turn=1, prompt=c.get("prompt", ""), response=c.get("response", ""),
        )
        if guard:
            v = await llama_guard_verdict(client, attempt, mock=mock)
        else:
            v = await breach_judge(client, attempt, mock=mock)
        label = bool(c.get("label_breached"))
        y_true.append(label)
        y_pred.append(bool(v.breached))
        sev_true.append(str(c.get("label_severity", "none")))
        sev_pred.append(str(v.severity or "none"))
        detail.append({
            "id": c["id"], "strategy": c.get("strategy"),
            "label_breached": label, "judge_breached": bool(v.breached),
            "agree": label == bool(v.breached),
            "label_severity": c.get("label_severity"), "judge_severity": v.severity,
        })

    metrics = stats.binary_classification_metrics(y_true, y_pred)
    kappa = stats.cohen_kappa(y_true, y_pred)
    severity_kappa = stats.cohen_kappa(sev_true, sev_pred)
    reliable = metrics["f1"] >= reliable_f1
    return {
        "judge": "llama_guard" if guard else "model",
        "mock": mock,
        "n": metrics["n"],
        "metrics": metrics,
        "breach_kappa": kappa,
        "severity_kappa": severity_kappa,
        "reliable": reliable,
        "reliable_threshold_f1": reliable_f1,
        "flags": ([] if reliable else
                  [f"judge F1 {metrics['f1']:.2f} < {reliable_f1:.2f} — not reliable enough to gate on"]),
        "disagreements": [d for d in detail if not d["agree"]],
        "detail": detail,
    }
