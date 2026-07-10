"""Invoice PDF generation for the invoice_issued email."""
from __future__ import annotations

from src.infrastructure.email.pdf import render_invoice_pdf


def test_render_invoice_pdf_produces_a_pdf() -> None:
    pdf = render_invoice_pdf(
        {
            "invoice_number": "INV-ABC123",
            "customer_name": "Acme Ltd",
            "currency": "KES",
            "total": "1500.00",
            "balance_due": "1500.00",
            "due_date": "2026-08-01",
        }
    )
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")   # valid PDF magic bytes
    assert len(pdf) > 500


def test_render_invoice_pdf_tolerates_missing_optional_fields() -> None:
    # No customer_name / due_date — the template guards these.
    pdf = render_invoice_pdf(
        {
            "invoice_number": "INV-XYZ",
            "currency": "KES",
            "total": "10.00",
            "balance_due": "10.00",
        }
    )
    assert pdf.startswith(b"%PDF")
