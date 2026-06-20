"""Guards for README badge row and the quickstart notebook (issue #31)."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
NOTEBOOK = REPO_ROOT / "examples" / "notebooks" / "quickstart.ipynb"


def test_readme_has_at_least_four_badges():
    text = README.read_text(encoding="utf-8")
    # Markdown image-in-link badges: [![alt](img)](href)
    badges = re.findall(r"\[!\[[^\]]*\]\([^)]+\)\]\([^)]+\)", text)
    assert len(badges) >= 4, f"expected >=4 badges, found {len(badges)}"


def test_readme_quickstart_callout_points_at_mock_demo():
    text = README.read_text(encoding="utf-8")
    assert "Quickstart in 30 seconds" in text
    assert "--mock" in text
    assert "examples/everyday_assistant/config.yaml" in text


def test_notebook_is_valid_json():
    with NOTEBOOK.open(encoding="utf-8") as fh:
        nb = json.load(fh)
    assert nb["nbformat"] == 4
    assert isinstance(nb["cells"], list) and nb["cells"]


def test_notebook_runs_install_and_mock_demo():
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    sources = "".join(
        "".join(cell.get("source", []))
        for cell in nb["cells"]
        if cell.get("cell_type") == "code"
    )
    assert "!pip install promptpolygraph" in sources
    assert (
        "!polygraph all --config examples/everyday_assistant/config.yaml --mock --format md"
        in sources
    )


def test_notebook_notes_colab_badge():
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    text = json.dumps(nb)
    assert "colab.research.google.com" in text
