"""Jinja2 rendering for transactional emails.

Each email ``template`` name resolves to a pair — ``{name}.html`` and
``{name}.txt`` — under ``domains/notifications/templates``, so every message ships
both an HTML part and a plain-text fallback. HTML is autoescaped; the ``.txt``
template is not (plain text needs no escaping).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

# .../src/infrastructure/email/renderer.py → parents[2] == .../src
_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[2] / "domains" / "notifications" / "templates"
)


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(template: str, context: dict[str, Any]) -> tuple[str, str]:
    """Return ``(html, text)`` for *template*. Raises if either part is missing."""
    env = _env()
    html = env.get_template(f"{template}.html").render(**context)
    text = env.get_template(f"{template}.txt").render(**context)
    return html, text
