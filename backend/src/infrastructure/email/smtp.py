"""Gmail SMTP transport (async).

Builds a multipart (text + HTML) message from a rendered template and sends it
over STARTTLS with an app password. When ``MAIL_ENABLED`` is false the message is
rendered and logged but no SMTP connection is opened — so dev and CI never send
real mail. Any SMTP failure propagates to the caller (the flush task), which
handles retry / dead-letter.
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

import aiosmtplib

from src.core.config import settings
from src.core.logging import logger
from src.infrastructure.email.renderer import render


def _build_message(
    *,
    to_email: str,
    to_name: str | None,
    subject: str,
    html: str,
    text: str,
    unsubscribe_url: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    from_addr = settings.MAIL_FROM_ADDRESS or settings.SMTP_USERNAME or "noreply@finguard.local"
    msg["From"] = f"{settings.MAIL_FROM_NAME} <{from_addr}>"
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg["Subject"] = subject
    # Reply-To + explicit Message-ID/Date improve deliverability (some MTAs
    # penalise their absence).
    msg["Reply-To"] = settings.MAIL_REPLY_TO or from_addr
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    msg["Date"] = formatdate(localtime=True)
    # One-click unsubscribe (RFC 8058) for suppressible mail — a strong Gmail/
    # Yahoo deliverability signal. Present only when the email carries an
    # unsubscribe link (approval / reminder categories).
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)                       # plain-text part
    msg.add_alternative(html, subtype="html")   # richer HTML alternative
    return msg


async def send_email(
    *,
    to_email: str,
    to_name: str | None,
    subject: str,
    template: str,
    context: dict[str, Any],
) -> None:
    """Render *template* and deliver it (or dry-run log it when mail is disabled)."""
    html, text = render(template, context)
    unsubscribe_url = context.get("unsubscribe_url")
    msg = _build_message(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html=html,
        text=text,
        unsubscribe_url=unsubscribe_url if isinstance(unsubscribe_url, str) else None,
    )

    # Attach a PDF for issued invoices (best-effort — a PDF failure must never
    # block delivery of the email itself).
    if template == "invoice_issued":
        try:
            from src.infrastructure.email.pdf import render_invoice_pdf  # noqa: PLC0415

            pdf = render_invoice_pdf(context)
            msg.add_attachment(
                pdf,
                maintype="application",
                subtype="pdf",
                filename=f"invoice_{context.get('invoice_number', 'finguard')}.pdf",
            )
        except Exception as exc:  # noqa: BLE001 — never fail the send over a PDF
            logger.warning("invoice PDF attach failed; sending without it", error=str(exc))

    if not settings.MAIL_ENABLED:
        logger.info(
            "email dry-run (MAIL_ENABLED=false) — not sent",
            to=to_email,
            subject=subject,
            template=template,
        )
        return

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_APP_PASSWORD,
        start_tls=True,
    )
    logger.info("email sent", to=to_email, subject=subject, template=template)
