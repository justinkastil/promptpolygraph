"""Jinja2 environment construction for the report templates.

`render_template` resolves the template via a `ChoiceLoader`: a user-supplied
`template_dir` (if given) takes precedence, falling back to the named built-in
template set packaged under `promptpolygraph/report/templates/<template>/`.
Built-in sets ship as package data (`PackageLoader` finds them in an installed
wheel). HTML autoescaping is enabled for `.html`/`.j2` templates so arbitrary
prompts/responses cannot break the markup; the Markdown template opts out of
escaping by being rendered through the same env with autoescape keyed on the
file extension.
"""

from __future__ import annotations

from typing import Optional

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader


def _autoescape(name: Optional[str]) -> bool:
    """Autoescape HTML templates (e.g. 'report.html.j2'), not Markdown ones."""
    if not name:
        return False
    return ".html" in name or name.endswith((".htm", ".xml"))


def render_template(
    template_name: str,
    context: dict,
    *,
    template: str = "default",
    template_dir: Optional[str] = None,
) -> str:
    """Render `template_name` (e.g. 'report.html.j2') against `context`.

    `template` selects the built-in set ('default' or 'minimal'); `template_dir`,
    if given, is searched first so a user directory can override built-ins.
    """
    loaders = []
    if template_dir:
        loaders.append(FileSystemLoader(template_dir))
    loaders.append(PackageLoader("promptpolygraph.report", f"templates/{template}"))

    env = Environment(
        loader=ChoiceLoader(loaders),
        autoescape=_autoescape,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(template_name).render(**context)
