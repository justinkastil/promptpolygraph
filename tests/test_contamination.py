"""Contamination + judge-circularity detection. Offline and deterministic."""

from __future__ import annotations

from promptpolygraph.corpus import check_contamination
from promptpolygraph.corpus.contamination import _jaccard, _tokens
from promptpolygraph.models import Case


def _case(prompt: str, cid: str = "", category: str = "general") -> Case:
    return Case(id=cid or prompt, prompt=prompt, category=category)


REFERENCE = [
    "How do I reset my account password",
    "What are the supported file storage limits",
    "Explain how billing cycles roll over each month",
]


def test_planted_exact_overlap_detected():
    cases = [
        _case("How do I reset my account password", "c1"),
        _case("Where is the weather forecast for tomorrow", "c2"),
    ]
    report = check_contamination(cases, reference=REFERENCE)
    ov = report["reference_overlap"]
    assert ov["overlap_count"] == 1
    assert ov["exact_count"] == 1
    assert report["contaminated"] is True
    assert ov["matches"][0]["case_id"] == "c1"
    assert ov["matches"][0]["exact"] is True


def test_planted_near_duplicate_detected():
    # One added word against a longer reference entry — token-set Jaccard stays
    # above threshold but is not exact.
    cases = [_case("Explain clearly how billing cycles roll over each month", "near1")]
    report = check_contamination(cases, reference=REFERENCE)
    ov = report["reference_overlap"]
    assert ov["overlap_count"] == 1
    assert ov["exact_count"] == 0
    assert ov["matches"][0]["case_id"] == "near1"
    assert 0.8 <= ov["matches"][0]["similarity"] < 1.0


def test_disjoint_corpus_reports_zero_overlap():
    cases = [
        _case("Recommend a hiking trail near the coast", "d1"),
        _case("Translate this sentence into French", "d2"),
    ]
    report = check_contamination(cases, reference=REFERENCE)
    ov = report["reference_overlap"]
    assert ov["overlap_count"] == 0
    assert ov["overlap_rate"] == 0.0
    assert report["contaminated"] is False
    assert report["caveat"] == "No contamination signals detected."


def test_same_model_circularity_warning_fires():
    cases = [_case("Recommend a hiking trail near the coast", "d1")]
    report = check_contamination(
        cases, generation_model="local-model-x", judge_model="local-model-x"
    )
    circ = report["judge_circularity"]
    assert circ["same_model"] is True
    assert report["contaminated"] is True
    assert "self-referential" in report["caveat"]


def test_distinct_models_no_circularity():
    cases = [_case("Recommend a hiking trail near the coast", "d1")]
    report = check_contamination(
        cases, generation_model="model-a", judge_model="model-b"
    )
    assert report["judge_circularity"]["same_model"] is False
    assert report["contaminated"] is False


def test_missing_model_does_not_flag_circularity():
    cases = [_case("Recommend a hiking trail near the coast", "d1")]
    report = check_contamination(cases, generation_model=None, judge_model=None)
    assert report["judge_circularity"]["same_model"] is False


def test_seed_bank_leak_flagged():
    seed_bank = [
        {"prompt": "Summarize the latest release notes", "category": "general"},
        {"prompt": "List the open support tickets", "category": "general"},
    ]
    cases = [
        # Near-duplicate of a seed entry -> leaked.
        _case("summarize the latest release notes please", "leak1"),
        # Genuinely novel -> not leaked.
        _case("Recommend a hiking trail near the coast", "ok1"),
    ]
    report = check_contamination(cases, seed_bank=seed_bank)
    seed = report["seed_leakage"]
    assert seed["leak_count"] == 1
    assert seed["leaks"][0]["case_id"] == "leak1"
    assert report["contaminated"] is True
    assert "seed-bank" in report["caveat"]


def test_reference_path_read_from_file(tmp_path):
    ref_file = tmp_path / "reference.txt"
    ref_file.write_text("\n".join(REFERENCE) + "\n", encoding="utf-8")
    cases = [_case("How do I reset my account password", "c1")]
    report = check_contamination(cases, reference_path=str(ref_file))
    assert report["reference_overlap"]["overlap_count"] == 1


def test_deterministic_repeat_runs():
    cases = [
        _case("How do I reset my account password", "c1"),
        _case("Recommend a hiking trail near the coast", "c2"),
    ]
    a = check_contamination(cases, reference=REFERENCE, generation_model="m", judge_model="m")
    b = check_contamination(cases, reference=REFERENCE, generation_model="m", judge_model="m")
    assert a == b


def test_empty_corpus_safe():
    report = check_contamination([], reference=REFERENCE)
    assert report["reference_overlap"]["overlap_rate"] == 0.0
    assert report["contaminated"] is False


def test_threshold_tightening_drops_weak_matches():
    cases = [_case("how do i reset the account password", "near1")]
    loose = check_contamination(cases, reference=REFERENCE, threshold=0.5)
    strict = check_contamination(cases, reference=REFERENCE, threshold=0.95)
    assert loose["reference_overlap"]["overlap_count"] == 1
    assert strict["reference_overlap"]["overlap_count"] == 0


def test_token_jaccard_helpers():
    assert _jaccard(_tokens("a b c"), _tokens("a b c")) == 1.0
    assert _jaccard(_tokens("a b c"), _tokens("x y z")) == 0.0
    assert _tokens("Hello, World!") == _tokens("hello world")
