from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text())


def test_action_yml_parses_and_is_composite() -> None:
    action = _load("action.yml")
    assert action["runs"]["using"] == "composite"
    assert isinstance(action["runs"]["steps"], list) and action["runs"]["steps"]


def test_action_declares_documented_inputs_with_defaults() -> None:
    inputs = _load("action.yml")["inputs"]
    assert inputs["config"]["required"] is True
    defaults = {
        "mode": "",
        "format": "md,html",
        "baseline": "",
        "mock": "false",
        "python-version": "3.12",
        "extras": "",
        "source": "promptpolygraph",
    }
    for name, default in defaults.items():
        assert inputs[name]["default"] == default


def test_action_declares_outputs() -> None:
    outputs = _load("action.yml")["outputs"]
    assert set(outputs) == {"verdict", "report-dir"}


def test_example_workflow_parses() -> None:
    wf = _load(".github/workflows/example-action.yml")
    assert "jobs" in wf
