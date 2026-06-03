"""Read a local source tree to give the forensic audit real code to cite.

`code_path` points at a checkout on the local filesystem — in CI that is just
the already-checked-out workspace (`code_path: "."`), so no credentials are
ever involved. This module walks that tree once, builds a repository map, and
selects the most relevant file excerpts for a set of query terms (the failing
category + rubric dimensions + red-flag keywords) within a byte budget, so the
agent can name concrete `file:line` root causes instead of guessing.

(Optional future upgrade, intentionally not built: a git source that clones a
private repo by URL + token for remote workers with no checked-out workspace.)
"""

from __future__ import annotations

import re
from pathlib import Path

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", "site-packages", ".tox", "coverage", "htmlcov", ".next",
    ".cache", "vendor", ".gradle", "Pods",
}
_SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".rb", ".php",
    ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".kt", ".kts", ".swift", ".scala",
    ".m", ".mm", ".sql", ".sh", ".yaml", ".yml", ".toml", ".tf", ".ex", ".exs",
}
_MAX_FILE_SIZE = 500_000  # skip very large files when scanning
_SAMPLE_BYTES = 4096      # bytes read per file for relevance scoring


def expand_terms(terms: list[str]) -> list[str]:
    """Lowercase, split snake/camel/path tokens, drop short/noise tokens."""
    out: set[str] = set()
    for t in terms:
        if not t:
            continue
        t = str(t).lower()
        out.add(t)
        for part in re.split(r"[^a-z0-9]+", t):
            out.add(part)
    # Drop sub-3-char tokens: 1-2 char substrings are noise for file ranking.
    return [t for t in out if len(t) >= 3]


class CodeIndex:
    """Walks a source tree once; serves a repo map + relevance-ranked excerpts."""

    def __init__(self, root: str, *, max_files: int = 4000):
        self.root = Path(root).expanduser()
        self.ok = self.root.exists()
        self._files: list[tuple[str, Path]] = []  # (relpath, abspath)
        self._sample: dict[str, str] = {}
        if not self.ok:
            return
        count = 0
        for p in sorted(self.root.rglob("*")):
            if count >= max_files:
                break
            if p.is_dir():
                continue
            if any(part in _IGNORE_DIRS for part in p.relative_to(self.root).parts):
                continue
            if p.suffix.lower() not in _SOURCE_EXTS:
                continue
            try:
                if p.stat().st_size > _MAX_FILE_SIZE:
                    continue
                sample = p.read_text(encoding="utf-8", errors="ignore")[:_SAMPLE_BYTES]
            except OSError:
                continue
            rel = str(p.relative_to(self.root))
            self._files.append((rel, p))
            self._sample[rel] = sample.lower()
            count += 1

    def repo_map(self, max_entries: int = 400) -> str:
        rels = [rel for rel, _ in self._files]
        shown = rels[:max_entries]
        extra = len(rels) - len(shown)
        body = "\n".join(shown)
        if extra > 0:
            body += f"\n… (+{extra} more files)"
        return body

    def _score(self, rel: str, terms: list[str]) -> int:
        path_l = rel.lower()
        sample = self._sample.get(rel, "")
        score = 0
        for t in terms:
            score += path_l.count(t) * 5
            score += sample.count(t)
        return score

    def context(
        self,
        terms: list[str],
        *,
        max_files: int = 6,
        max_total_bytes: int = 36_000,
        max_file_bytes: int = 7_000,
    ) -> str:
        if not self._files:
            return ""
        terms = expand_terms(terms)
        ranked = sorted(
            ((self._score(rel, terms), rel, p) for rel, p in self._files),
            key=lambda x: x[0],
            reverse=True,
        )
        ranked = [r for r in ranked if r[0] > 0][:max_files]
        if not ranked:
            return ""
        blocks: list[str] = []
        used = 0
        for _score, rel, p in ranked:
            excerpt = _excerpt(p, terms, max_file_bytes)
            if not excerpt:
                continue
            block = f"=== {rel} ===\n{excerpt}"
            if used + len(block) > max_total_bytes:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)


def _excerpt(path: Path, terms: list[str], max_bytes: int) -> str:
    """Line-numbered excerpt, centered on the first term match when present."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    hit = None
    for i, line in enumerate(lines):
        ll = line.lower()
        if any(t in ll for t in terms):
            hit = i
            break
    if hit is None:
        window = lines[:160]
        start = 1
    else:
        lo = max(0, hit - 60)
        hi = min(len(lines), hit + 100)
        window = lines[lo:hi]
        start = lo + 1
    out_lines: list[str] = []
    size = 0
    for n, line in enumerate(window, start=start):
        rendered = f"{n:>5}| {line}"
        if size + len(rendered) + 1 > max_bytes:
            out_lines.append("      | … (truncated)")
            break
        out_lines.append(rendered)
        size += len(rendered) + 1
    return "\n".join(out_lines)


def build_code_context(
    code_path: str | None,
    terms: list[str],
    *,
    index: CodeIndex | None = None,
    include_map: bool = True,
) -> str:
    """Convenience: build a code-context string for one set of query terms.

    Pass a shared `index` to avoid re-walking the tree per category. Returns ""
    when no path is given or the path has no readable source — callers degrade
    gracefully (the audit still runs on the eval data alone).
    """
    if index is None:
        if not code_path:
            return ""
        index = CodeIndex(code_path)
    if not index.ok or not index._files:
        return ""
    parts: list[str] = []
    if include_map:
        parts.append("REPOSITORY MAP (paths relative to the source root):\n" + index.repo_map())
    excerpts = index.context(terms)
    if excerpts:
        parts.append("RELEVANT SOURCE EXCERPTS (cite as file:line):\n" + excerpts)
    return "\n\n".join(parts)
