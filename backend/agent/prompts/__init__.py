"""Prompt templates (*.md) filled at runtime with string.Template ($name placeholders)."""

from functools import cache
from pathlib import Path
from string import Template

_DIR = Path(__file__).parent


@cache
def _template(name):
    return Template((_DIR / f"{name}.md").read_text())


def render(name, **values):
    return _template(name).substitute(**values)
