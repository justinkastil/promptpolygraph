from __future__ import annotations

import csv
import json

from promptpolygraph.cli import main


def test_export_corpus_json(tmp_path):
    out = tmp_path / "prompts.json"
    rc = main(["export", "--corpus", "examples/everyday_assistant/corpus", "--out", str(out)])
    assert rc == 0 and out.exists()
    rows = json.loads(out.read_text())
    assert isinstance(rows, list) and len(rows) >= 36
    assert "prompt" in rows[0] and "category" in rows[0]
    assert "id" not in rows[0]  # ids excluded so the exported corpus is reusable


def test_export_prompts_only_and_jsonl(tmp_path):
    out = tmp_path / "p.jsonl"
    main(["export", "--corpus", "examples/everyday_assistant/corpus",
          "--out", str(out), "--format", "jsonl", "--prompts-only"])
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert lines and set(lines[0].keys()) == {"prompt", "category"}


def test_export_csv(tmp_path):
    out = tmp_path / "p.csv"
    main(["export", "--corpus", "examples/everyday_assistant/corpus",
          "--out", str(out), "--format", "csv"])
    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert rows and "prompt" in rows[0] and "category" in rows[0]
