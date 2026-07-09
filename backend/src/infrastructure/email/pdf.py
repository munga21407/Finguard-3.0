"""PDF generation for invoice emails (WeasyPrint).

Renders a single-page A4 invoice from the same context the ``invoice_issued``
email carries. Kept behind a best-effort call site — a PDF failure must never
block the email itself.
"""
from __future__ import annotations

from typing import Any

from src.infrastructure.email.renderer import _env


def render_invoice_pdf(context: dict[str, Any]) -> bytes:
    """Return PDF bytes for an invoice from its email context.

    WeasyPrint is imported lazily: it pulls in native libraries and is only needed
    on the invoice path, so other email sends don't pay the import cost.
    """
    from weasyprint import HTML  # type: ignore[import-untyped]  # noqa: PLC0415

    html = _env().get_template("invoice_pdf.html").render(**context)
    pdf: bytes = HTML(string=html).write_pdf()
    return pdf
