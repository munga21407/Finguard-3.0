"""Gmail SMTP transport (async).

Builds a multipart (text + HTML) message from a rendered template and sends it
over STARTTLS with an app password. When ``MAIL_ENABLED`` is false the message is
rendered and logged but no SMTP connection is opened — so dev and CI never send
real mail. Any SMTP failure propagates to the caller (the flush task), which
handles retry / dead-letter.
"""
from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import aiosmtplib

from src.core.config import settings
from src.core.logging import logger
from src.infrastructure.email.renderer import render


def _build_message(
    *, to_email: str, to_name: str | None, subject: str, html: str, text: str
) -> EmailMessage:
    msg = EmailMessage()
    from_addr = settings.MAIL_FROM_ADDRESS or settings.SMTP_USERNAME or "noreply@finguard.local"
    msg["From"] = f"{settings.MAIL_FROM_NAME} <{from_addr}>"
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg["Subject"] = subject
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
    msg = _build_message(
        to_email=to_email, to_name=to_name, subject=subject, html=html, text=text
    )

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
